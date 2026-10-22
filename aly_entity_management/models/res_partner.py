import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    aly_customer_type = fields.Selection(
        selection=[
            ('tenant', 'Tenant'),
            ('buyer', 'Buyer'),
            ('both', 'Tenant and Buyer'),
        ],
        string='Customer Type',
        tracking=True,
        index=True,
        help='Whether the customer rents units, buys units, or both. Chosen by the employee '
             'when registering the customer; used to filter and group customers. It does not '
             'restrict which reservations can be made for the customer.',
    )
    identity_type = fields.Selection(
        selection=[
            ('national_id', 'National ID'),
            ('iqama', 'Iqama'),
            ('passport', 'Passport'),
        ],
        string='Identity Type',
        tracking=True,
        help='Official document that identifies the customer. National ID is for '
             'citizens (10 digits starting with 1), Iqama for residents (10 digits '
             'starting with 2), Passport for visitors and foreign buyers.',
    )
    identity_number = fields.Char(
        string='Identity Number',
        tracking=True,
        index='btree_not_null',
        copy=False,
        help='Number of the identity document. It must be unique in the whole system, '
             'so the same person cannot be registered twice and a blacklisted customer '
             'cannot come back under a new record.',
    )
    aly_is_blacklisted = fields.Boolean(
        string='Blacklisted',
        tracking=True,
        copy=False,
        help='When set, the customer can no longer get new reservations or contracts. '
             'Invoices and payments of existing contracts and maintenance hours are '
             'still allowed, so the company can collect what is owed.',
    )
    aly_blacklist_reason = fields.Text(
        string='Blacklist Reason',
        tracking=True,
        copy=False,
        help='Why the customer was blacklisted. Required when the customer is '
             'blacklisted and shown in the error message when someone tries to reserve '
             'or contract for this customer.',
    )
    aly_reservation_ids = fields.One2many(
        comodel_name='aly.entity.reservation',
        inverse_name='partner_id',
        string='Reservations',
        help='All unit reservations made by or for this customer, in every state.',
    )
    aly_contract_ids = fields.One2many(
        comodel_name='aly.entity.contract',
        inverse_name='partner_id',
        string='Real Estate Contracts',
        help='All lease and sale contracts of this customer, in every state.',
    )
    aly_reservation_count = fields.Integer(
        string='Reservation Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of reservations of this customer, all states included.',
    )
    aly_lease_count = fields.Integer(
        string='Lease Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of lease contracts of this customer, all states included.',
    )
    aly_sale_count = fields.Integer(
        string='Purchase Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of sale contracts (units bought) of this customer, all states included.',
    )
    aly_unit_count = fields.Integer(
        string='Unit Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of distinct units this customer has reserved, leased or bought.',
    )
    aly_invoice_count = fields.Integer(
        string='Contract Invoice Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of invoices generated from the real estate contracts of this customer.',
    )
    aly_payment_count = fields.Integer(
        string='Contract Payment Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of payments reconciled with the real estate invoices of this customer.',
    )
    aly_signature_count = fields.Integer(
        string='Signature Count',
        compute='_compute_aly_counts',
        store=False,
        help='Number of contracts this customer signed, in the office or in the portal.',
    )
    aly_balance_due = fields.Monetary(
        string='Balance Due',
        currency_field='currency_id',
        compute='_compute_aly_counts',
        store=False,
        help='Amount still unpaid on the posted real estate invoices of this customer.',
    )

    _sql_constraints = [
        ('identity_number_uniq',
         'UNIQUE(identity_number)',
         'This identity number is already registered for another customer.'),
    ]

    def _compute_aly_counts(self):
        for partner in self:
            reservations = partner.aly_reservation_ids
            contracts = partner.aly_contract_ids
            invoices = contracts.invoice_ids
            posted = invoices.filtered(lambda move: move.state == 'posted')
            partner.aly_reservation_count = len(reservations)
            partner.aly_lease_count = len(contracts.filtered(lambda c: c.contract_type == 'lease'))
            partner.aly_sale_count = len(contracts.filtered(lambda c: c.contract_type == 'sale'))
            partner.aly_unit_count = len(reservations.unit_id | contracts.unit_id)
            partner.aly_invoice_count = len(invoices)
            partner.aly_payment_count = len(invoices.reconciled_payment_ids)
            partner.aly_balance_due = sum(posted.mapped('amount_residual'))
            partner.aly_signature_count = len(contracts.filtered('signed_on'))

    @api.constrains('identity_type', 'identity_number')
    def _check_identity_number_format(self):
        patterns = {
            'national_id': (r'^1\d{9}$', self.env._('A National ID must be 10 digits starting with 1.')),
            'iqama': (r'^2\d{9}$', self.env._('An Iqama number must be 10 digits starting with 2.')),
            'passport': (r'^[A-Za-z0-9]{6,12}$', self.env._('A passport number must be 6 to 12 letters or digits.')),
        }
        for partner in self:
            if not partner.identity_number:
                continue
            if not partner.identity_type:
                raise ValidationError(self.env._(
                    'Choose the identity type of %(name)s before entering the identity number.',
                    name=partner.display_name,
                ))
            pattern, message = patterns[partner.identity_type]
            if not re.match(pattern, partner.identity_number):
                raise ValidationError(message)

    @api.constrains('aly_is_blacklisted', 'aly_blacklist_reason')
    def _check_blacklist_reason(self):
        for partner in self:
            if partner.aly_is_blacklisted and not (partner.aly_blacklist_reason or '').strip():
                raise ValidationError(self.env._(
                    'Enter the reason why %(name)s is blacklisted.', name=partner.display_name,
                ))

    def write(self, vals):
        if {'aly_is_blacklisted', 'aly_blacklist_reason'} & set(vals) \
                and not self.env.su \
                and not self.env.user.has_group('aly_entity_management.group_aly_entity_user'):
            raise AccessError(self.env._('Only real estate staff can blacklist or un-blacklist a customer.'))
        return super().write(vals)

    def _aly_check_not_blacklisted(self):
        """Raise when one of the partners is blacklisted (blocks reservations and contracts)."""
        for partner in self:
            commercial = partner.commercial_partner_id
            if partner.aly_is_blacklisted or commercial.aly_is_blacklisted:
                blocked = partner if partner.aly_is_blacklisted else commercial
                raise UserError(self.env._(
                    'The customer %(name)s is blacklisted: %(reason)s',
                    name=blocked.display_name,
                    reason=blocked.aly_blacklist_reason,
                ))

    def _aly_check_customer_data(self):
        """Mobile and identity are mandatory before a reservation is confirmed."""
        for partner in self:
            missing = []
            if not (partner.mobile or partner.phone):
                missing.append(self.env._('Mobile'))
            if not partner.identity_type:
                missing.append(self.env._('Identity Type'))
            if not partner.identity_number:
                missing.append(self.env._('Identity Number'))
            if missing:
                raise UserError(self.env._(
                    'Complete the data of %(name)s first: %(fields)s.',
                    name=partner.display_name,
                    fields=', '.join(missing),
                ))

    def _aly_open_action(self, xmlid, domain, context=None):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['domain'] = domain
        action['context'] = dict(context or {}, create=False)
        return action

    def action_aly_view_reservations(self):
        self.ensure_one()
        return self._aly_open_action(
            'aly_entity_management.aly_entity_reservation_action',
            [('partner_id', '=', self.id)],
            {'default_partner_id': self.id, 'search_default_filter_active': 1},
        )

    def action_aly_view_leases(self):
        self.ensure_one()
        return self._aly_open_action(
            'aly_entity_management.aly_entity_contract_action',
            [('partner_id', '=', self.id), ('contract_type', '=', 'lease')],
            {'search_default_filter_active': 1},
        )

    def action_aly_view_sales(self):
        self.ensure_one()
        return self._aly_open_action(
            'aly_entity_management.aly_entity_contract_action',
            [('partner_id', '=', self.id), ('contract_type', '=', 'sale')],
            {'search_default_filter_active': 1},
        )

    def action_aly_view_units(self):
        self.ensure_one()
        units = self.aly_reservation_ids.unit_id | self.aly_contract_ids.unit_id
        return self._aly_open_action(
            'aly_entity_management.aly_entity_unit_action',
            [('id', 'in', units.ids)],
        )

    def action_aly_view_invoices(self):
        self.ensure_one()
        return self._aly_open_action(
            'aly_entity_management.aly_entity_contract_invoice_action',
            [('aly_contract_id.partner_id', '=', self.id)],
        )

    def action_aly_view_unpaid_invoices(self):
        self.ensure_one()
        return self._aly_open_action(
            'aly_entity_management.aly_entity_contract_invoice_action',
            [('aly_contract_id.partner_id', '=', self.id),
             ('state', '=', 'posted'),
             ('payment_state', 'not in', ('paid', 'in_payment', 'reversed'))],
        )

    def action_aly_view_signatures(self):
        self.ensure_one()
        return self.env['aly.entity.contract']._aly_action_signatures([('partner_id', '=', self.id)])

    def action_aly_view_payments(self):
        self.ensure_one()
        payments = self.aly_contract_ids.invoice_ids.reconciled_payment_ids
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_account_payments')
        action['domain'] = [('id', 'in', payments.ids)]
        action['context'] = {'create': False}
        return action

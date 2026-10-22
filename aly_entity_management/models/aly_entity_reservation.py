from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .aly_entity_unit import ACTIVE_RESERVATION_STATES


class AlyEntityReservation(models.Model):
    _name = 'aly.entity.reservation'
    _description = 'Real Estate Reservation'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin', 'aly.entity.navigation.mixin']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='/',
        index='trigram',
        help='Unique reference given by the system when the reservation is created, '
             'e.g. RES/2027/0001.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        required=True,
        tracking=True,
        index=True,
        ondelete='restrict',
        help='Tenant or buyer who reserves the unit. Blacklisted customers cannot get '
             'their reservation confirmed.',
    )
    unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        required=True,
        tracking=True,
        index=True,
        ondelete='restrict',
        help='Unit being reserved. Sold units are marked "(Sold)"; picking one is '
             'allowed but the reservation is refused when it is confirmed.',
    )
    entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        related='unit_id.entity_id',
        store=True,
        index=True,
        help='Property of the reserved unit, used to search and group reservations.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='unit_id.company_id',
        store=True,
        index=True,
        help='Company of the unit. Users of other companies cannot see the reservation.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        help='Currency of the unit prices shown on the reservation.',
    )
    contract_type = fields.Selection(
        selection=[
            ('lease', 'Lease'),
            ('sale', 'Sale'),
        ],
        string='Reservation Type',
        required=True,
        default='lease',
        tracking=True,
        help='Lease reserves the unit for a period (start and end date). Sale reserves '
             'it for a purchase, with a single handover date.',
    )
    date_start = fields.Date(
        string='Start / Handover Date',
        required=True,
        tracking=True,
        default=fields.Date.context_today,
        help='For a lease, the first day of the requested period. For a sale, the day '
             'the unit is handed over to the buyer.',
    )
    date_end = fields.Date(
        string='End Date',
        tracking=True,
        help='Last day of the requested lease period (included). Not used for sales.',
    )
    unit_yearly_rent = fields.Monetary(
        string='Unit Yearly Rent',
        related='unit_id.yearly_rent',
        currency_field='currency_id',
        help='Current yearly rent of the unit, for information. The contract copies it '
             'and may adjust it.',
    )
    unit_sale_price = fields.Monetary(
        string='Unit Sale Price',
        related='unit_id.sale_price',
        currency_field='currency_id',
        help='Current sale price of the unit, for information. The contract copies it '
             'and may adjust it.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('awaiting_signature', 'Awaiting Signature'),
            ('signed', 'Signed'),
            ('contracted', 'Contracted'),
            ('cancelled', 'Cancelled'),
            ('expired', 'Expired'),
        ],
        string='Status',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
        index=True,
        help='Draft: request not reviewed yet (portal requests start here). Confirmed: '
             'reviewed by an employee, the unit is reserved. Awaiting Signature: the '
             'contract was sent to the customer. Signed: the customer signed it. '
             'Contracted: a manager approved the contract. Expired: the validity passed '
             'without a signature. Cancelled: stopped by an employee.',
    )
    expiry_date = fields.Date(
        string='Valid Until',
        readonly=True,
        copy=False,
        tracking=True,
        help='Last day the confirmed reservation waits for the customer signature. Set '
             'on confirmation from the company validity days; after this day the '
             'reservation expires and its unsigned contract is cancelled.',
    )
    expiry_reminder_sent = fields.Boolean(
        string='Expiry Reminder Sent',
        readonly=True,
        copy=False,
        help='Technical flag so the property manager gets only one reminder before the '
             'reservation expires.',
    )
    confirmed_on = fields.Datetime(
        string='Confirmed On',
        readonly=True,
        copy=False,
        help='Date and time the reservation was confirmed.',
    )
    confirmed_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Confirmed By',
        readonly=True,
        copy=False,
        ondelete='set null',
        help='Employee who confirmed the reservation.',
    )
    cancel_reason = fields.Text(
        string='Cancellation Reason',
        readonly=True,
        copy=False,
        tracking=True,
        help='Why the reservation was cancelled or expired.',
    )
    is_portal_request = fields.Boolean(
        string='Portal Request',
        readonly=True,
        copy=False,
        help='The customer created this reservation from the portal; it waits for an '
             'employee to confirm it.',
    )
    contract_ids = fields.One2many(
        comodel_name='aly.entity.contract',
        inverse_name='reservation_id',
        string='Contracts',
        help='Contracts created from this reservation, including cancelled ones.',
    )
    contract_id = fields.Many2one(
        comodel_name='aly.entity.contract',
        string='Contract',
        compute='_compute_contract_id',
        store=False,
        help='The current (not cancelled) contract created from this reservation.',
    )
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_invoice_count',
        store=False,
        help='Number of invoices of the contracts created from this reservation.',
    )
    manager_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Property Manager',
        related='entity_id.manager_id.user_id',
        help='User of the property manager, who receives the reservation reminders.',
    )
    partner_is_blacklisted = fields.Boolean(
        string='Customer Blacklisted',
        related='partner_id.aly_is_blacklisted',
        help='Shows a warning banner when the customer is blacklisted.',
    )
    partner_blacklist_reason = fields.Text(
        string='Customer Blacklist Reason',
        related='partner_id.aly_blacklist_reason',
        help='Reason the customer was blacklisted, shown in the warning banner.',
    )
    conflict_warning = fields.Char(
        string='Availability Warning',
        compute='_compute_conflict_warning',
        store=False,
        help='Shown when an approved contract now occupies the requested period. The '
             'reservation is not cancelled automatically; the employee decides.',
    )

    @api.depends('contract_ids.state')
    def _compute_contract_id(self):
        for reservation in self:
            reservation.contract_id = reservation.contract_ids.filtered(
                lambda c: c.state != 'cancelled'
            ).sorted('id', reverse=True)[:1]

    def _compute_invoice_count(self):
        for reservation in self:
            reservation.invoice_count = len(reservation.contract_ids.invoice_ids)

    @api.depends('unit_id', 'contract_type', 'date_start', 'date_end', 'state')
    def _compute_conflict_warning(self):
        for reservation in self:
            warning = ''
            if reservation.unit_id and reservation.date_start \
                    and reservation.state in ('draft',) + ACTIVE_RESERVATION_STATES:
                warning = reservation.unit_id._aly_get_conflict(
                    reservation.contract_type,
                    reservation.date_start,
                    reservation._aly_period_end(),
                    exclude_contract=reservation.contract_id,
                )
            reservation.conflict_warning = warning

    @api.constrains('contract_type', 'date_start', 'date_end')
    def _check_dates(self):
        for reservation in self:
            if reservation.contract_type == 'lease':
                if not reservation.date_end:
                    raise ValidationError(self.env._('A lease reservation needs an end date.'))
                if reservation.date_end <= reservation.date_start:
                    raise ValidationError(self.env._('The end date must be after the start date.'))

    @api.onchange('unit_id')
    def _onchange_unit_id(self):
        if self.unit_id:
            if self.contract_type == 'lease' and not self.unit_id.is_for_rent and self.unit_id.is_for_sale:
                self.contract_type = 'sale'
            elif self.contract_type == 'sale' and not self.unit_id.is_for_sale and self.unit_id.is_for_rent:
                self.contract_type = 'lease'

    @api.onchange('contract_type', 'date_start')
    def _onchange_period(self):
        if self.contract_type == 'sale':
            self.date_end = False
        elif self.date_start and not self.date_end:
            self.date_end = self.date_start + relativedelta(years=1, days=-1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('aly.entity.reservation') or '/'
            if vals.get('contract_type') == 'sale':
                vals['date_end'] = False
        return super().create(vals_list)

    def unlink(self):
        if self.filtered(lambda r: r.state != 'draft'):
            raise UserError(self.env._('Only draft reservations can be deleted; cancel the others instead.'))
        return super().unlink()

    def _get_report_base_filename(self):
        self.ensure_one()
        return f'Reservation {self.name}'

    def _compute_access_url(self):
        super()._compute_access_url()
        for reservation in self:
            reservation.access_url = f'/my/reservations/{reservation.id}'

    def _aly_period_end(self):
        """Last day used for the conflict check: the end date for a lease, the handover
        date itself for a sale."""
        self.ensure_one()
        return self.date_end if self.contract_type == 'lease' else self.date_start

    def _aly_check_can_be_reserved(self):
        for reservation in self:
            reservation.partner_id._aly_check_not_blacklisted()
            reservation.unit_id._aly_check_availability(
                reservation.contract_type, reservation.date_start, reservation._aly_period_end(),
            )


    def action_confirm(self):
        for reservation in self:
            if reservation.state != 'draft':
                raise UserError(self.env._('Only draft reservations can be confirmed.'))
            reservation.partner_id._aly_check_customer_data()
        self._aly_check_can_be_reserved()
        today = fields.Date.context_today(self)
        template = self.env.ref('aly_entity_management.mail_template_reservation_confirmed', raise_if_not_found=False)
        for reservation in self:
            reservation.write({
                'state': 'confirmed',
                'confirmed_on': fields.Datetime.now(),
                'confirmed_by_id': self.env.user.id,
                'expiry_date': today + timedelta(days=reservation.company_id.aly_reservation_validity_days),
                'expiry_reminder_sent': False,
            })
            reservation.activity_feedback(['mail.mail_activity_data_todo'])
            if template:
                reservation.message_post_with_source(template, subtype_xmlid='mail.mt_comment')
        return True

    def action_create_contract(self):
        self.ensure_one()
        if self.state not in ACTIVE_RESERVATION_STATES:
            raise UserError(self.env._('A contract can only be created from a confirmed reservation.'))
        if not self.contract_id:
            self.partner_id._aly_check_not_blacklisted()
            self.env['aly.entity.contract'].create({'reservation_id': self.id})
        return self.action_view_contract()

    def action_view_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aly.entity.contract',
            'res_id': self.contract_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aly_entity_management.aly_entity_contract_invoice_action')
        action['domain'] = [('aly_contract_id', 'in', self.contract_ids.ids)]
        action['context'] = {'create': False}
        return action

    def action_cancel(self):
        self.ensure_one()
        return self.env['aly.entity.cancel.wizard'].with_context(
            active_model=self._name, active_ids=self.ids,
        )._aly_open()

    def _aly_cancel(self, reason, state='cancelled'):
        if self.filtered(lambda r: r.state == 'contracted'):
            raise UserError(self.env._('A contracted reservation cannot be cancelled.'))
        self.write({'state': state, 'cancel_reason': reason})
        open_contracts = self.contract_ids.filtered(lambda c: c.state in ('draft', 'awaiting_signature', 'signed'))
        open_contracts.with_context(aly_from_reservation=True)._aly_cancel(reason)
        self.activity_unlink(['mail.mail_activity_data_todo'])

    def action_print(self):
        self.ensure_one()
        return self.env.ref('aly_entity_management.action_report_aly_entity_reservation').report_action(self)


    @api.model
    def _cron_expire_reservations(self):
        today = fields.Date.context_today(self)
        waiting = self.search([('state', 'in', ('confirmed', 'awaiting_signature'))])
        expired = waiting.filtered(lambda r: r.expiry_date and r.expiry_date < today)
        for reservation in expired:
            reservation._aly_cancel(
                self.env._('Expired on %(date)s without customer signature.', date=reservation.expiry_date),
                state='expired',
            )
        to_remind = (waiting - expired).filtered(
            lambda r: r.expiry_date and not r.expiry_reminder_sent and r.expiry_date - timedelta(days=1) <= today
        )
        for reservation in to_remind:
            if reservation.manager_user_id:
                reservation.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=reservation.expiry_date,
                    summary=self.env._('Reservation expires soon'),
                    note=self.env._(
                        'Reservation %(name)s of %(customer)s expires on %(date)s if the contract is not signed.',
                        name=reservation.name, customer=reservation.partner_id.name, date=reservation.expiry_date,
                    ),
                    user_id=reservation.manager_user_id.id,
                )
            reservation.expiry_reminder_sent = True

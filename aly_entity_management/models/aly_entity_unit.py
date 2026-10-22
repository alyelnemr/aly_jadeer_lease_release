from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_date

ACTIVE_RESERVATION_STATES = ('confirmed', 'awaiting_signature', 'signed')


class AlyEntityUnit(models.Model):
    _name = 'aly.entity.unit'
    _description = 'Real Estate Unit'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin', 'aly.entity.navigation.mixin']
    _order = 'entity_id, floor, name'
    _check_company_auto = True

    name = fields.Char(
        string='Unit Number',
        required=True,
        tracking=True,
        index='trigram',
        help='Number or name of the unit inside its property, e.g. "A-101". Unique '
             'within the property.',
    )
    entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        required=True,
        tracking=True,
        index=True,
        ondelete='restrict',
        help='Property the unit belongs to. A property that still has units cannot be '
             'deleted, only archived.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='entity_id.company_id',
        store=True,
        index=True,
        help='Company of the property. Decides who can see the unit and which company '
             'its contracts and invoices belong to.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        help='Currency of the rent and sale price, taken from the company.',
    )
    unit_type = fields.Selection(
        selection=[
            ('residential', 'Residential'),
            ('commercial', 'Commercial'),
        ],
        string='Unit Type',
        required=True,
        default='residential',
        tracking=True,
        help='Residential units are homes (apartments, villas); commercial units are '
             'shops and offices. Used to filter units and in the reports.',
    )
    floor = fields.Selection(
        selection=[
            ('0', 'Ground Floor'),
            ('1', '1st Floor'),
            ('2', '2nd Floor'),
            ('3', '3rd Floor'),
            ('4', '4th Floor'),
            ('5', '5th Floor'),
            ('6', '6th Floor'),
        ],
        string='Floor',
        required=True,
        default='0',
        help='Floor on which the unit is located, from the ground floor up to the 6th floor.',
    )
    area = fields.Float(
        string='Area (m²)',
        required=True,
        digits=(10, 2),
        help='Floor area of the unit in square meters. Must be greater than zero.',
    )
    rooms = fields.Integer(
        string='Rooms',
        required=True,
        default=1,
        help='Number of rooms of the unit. Must be at least one.',
    )
    is_for_rent = fields.Boolean(
        string='For Rent',
        default=True,
        tracking=True,
        help='The unit is offered for lease. Lease reservations are only accepted when '
             'this is checked, and the yearly rent becomes mandatory.',
    )
    is_for_sale = fields.Boolean(
        string='For Sale',
        tracking=True,
        help='The unit is offered for sale. Sale reservations are only accepted when '
             'this is checked, and the sale price becomes mandatory.',
    )
    yearly_rent = fields.Monetary(
        string='Yearly Rent',
        currency_field='currency_id',
        tracking=True,
        help='Rent for one year. Copied to new lease contracts (where it can still be '
             'adjusted) and used as the potential value of the unit when it is available.',
    )
    sale_price = fields.Monetary(
        string='Sale Price',
        currency_field='currency_id',
        tracking=True,
        help='Asking price of the unit. Copied to new sale contracts, where it can still '
             'be adjusted before the contract is sent.',
    )
    state = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('reserved', 'Reserved'),
            ('leased', 'Leased'),
            ('sold', 'Sold'),
        ],
        string='Status',
        compute='_compute_state',
        store=True,
        index=True,
        tracking=True,
        help='Computed by the system for today, never typed: Sold when a sale contract '
             'is approved, Leased when an approved lease contract covers today, Reserved '
             'when an active reservation covers today, otherwise Available. A daily job '
             'refreshes it because it changes with time alone.',
    )
    image_ids = fields.One2many(
        comodel_name='aly.entity.unit.image',
        inverse_name='unit_id',
        string='Gallery',
        help='Extra photos of the unit (rooms, kitchen, view), shown on the unit form '
             'and on the customer portal.',
    )
    reservation_ids = fields.One2many(
        comodel_name='aly.entity.reservation',
        inverse_name='unit_id',
        string='Reservations',
        help='All reservations of the unit, in every state.',
    )
    contract_ids = fields.One2many(
        comodel_name='aly.entity.contract',
        inverse_name='unit_id',
        string='Contracts',
        help='All lease and sale contracts of the unit, in every state.',
    )
    occupancy_contract_ids = fields.Many2many(
        comodel_name='aly.entity.contract',
        string='Approved Contracts',
        compute='_compute_occupancy',
        store=False,
        help='Approved contracts that are running now or start later. These periods '
             'block new reservations.',
    )
    occupancy_reservation_ids = fields.Many2many(
        comodel_name='aly.entity.reservation',
        string='Active Reservations',
        compute='_compute_occupancy',
        store=False,
        help='Confirmed reservations (not yet contracted) that are running now or start '
             'later. They do not block other reservations.',
    )
    reservation_count = fields.Integer(
        string='Reservation Count',
        compute='_compute_counts',
        store=False,
        help='Number of reservations of the unit, all states included.',
    )
    contract_count = fields.Integer(
        string='Contract Count',
        compute='_compute_counts',
        store=False,
        help='Number of contracts of the unit, all states included.',
    )
    maintenance_count = fields.Integer(
        string='Maintenance Requests',
        compute='_compute_counts',
        store=False,
        help='Number of maintenance requests of this unit, all states included.',
    )
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_counts',
        store=False,
        help='Number of invoices generated from the lease and sale contracts of this unit, '
             'drafts included.',
    )
    signature_count = fields.Integer(
        string='Signature Count',
        compute='_compute_counts',
        store=False,
        help='Number of contracts of this unit signed by a customer, in the office or in the portal.',
    )
    payment_count = fields.Integer(
        string='Payment Count',
        compute='_compute_counts',
        store=False,
        help='Number of customer payments reconciled with the invoices of this unit.',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
        help='Archive the unit instead of deleting it, so its history stays available.',
    )

    _sql_constraints = [
        ('name_entity_uniq',
         'UNIQUE(name, entity_id)',
         'The unit number must be unique within its property.'),
        ('area_positive',
         'CHECK(area > 0)',
         'The unit area must be greater than zero.'),
        ('rooms_positive',
         'CHECK(rooms > 0)',
         'The number of rooms must be greater than zero.'),
    ]

    @api.depends(
        'contract_ids.state', 'contract_ids.contract_type',
        'contract_ids.date_start', 'contract_ids.date_end',
        'reservation_ids.state', 'reservation_ids.contract_type',
        'reservation_ids.date_start', 'reservation_ids.date_end',
    )
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for unit in self:
            unit.state = unit._aly_state_on(today)

    def _aly_state_on(self, day):
        self.ensure_one()
        approved = self.contract_ids.filtered(lambda c: c.state == 'approved')
        if approved.filtered(lambda c: c.contract_type == 'lease' and c.date_start <= day <= c.date_end):
            return 'leased'
        if approved.filtered(lambda c: c.contract_type == 'sale'):
            return 'sold'
        reservations = self.reservation_ids.filtered(lambda r: r.state in ACTIVE_RESERVATION_STATES)
        for reservation in reservations:
            if reservation.contract_type == 'sale' or reservation.date_start <= day <= reservation.date_end:
                return 'reserved'
        return 'available'

    @api.depends('contract_ids.state', 'contract_ids.date_end', 'reservation_ids.state', 'reservation_ids.date_end')
    def _compute_occupancy(self):
        today = fields.Date.context_today(self)
        for unit in self:
            unit.occupancy_contract_ids = unit.contract_ids.filtered(
                lambda c: c.state == 'approved' and (c.contract_type == 'sale' or c.date_end >= today)
            ).sorted('date_start')
            unit.occupancy_reservation_ids = unit.reservation_ids.filtered(
                lambda r: r.state in ACTIVE_RESERVATION_STATES
                and (r.contract_type == 'sale' or r.date_end >= today)
            ).sorted('date_start')

    def _compute_counts(self):
        maintenance_data = dict(self.env['aly.entity.maintenance.request']._read_group(
            domain=[('unit_id', 'in', self.ids)],
            groupby=['unit_id'],
            aggregates=['__count'],
        ))
        for unit in self:
            unit.reservation_count = len(unit.reservation_ids)
            unit.contract_count = len(unit.contract_ids)
            unit.maintenance_count = maintenance_data.get(unit, 0)
            invoices = unit.contract_ids.invoice_ids
            unit.invoice_count = len(invoices)
            unit.payment_count = len(invoices.reconciled_payment_ids)
            unit.signature_count = len(unit.contract_ids.filtered('signed_on'))

    @api.constrains('is_for_rent', 'is_for_sale', 'yearly_rent', 'sale_price')
    def _check_offer(self):
        for unit in self:
            if not unit.is_for_rent and not unit.is_for_sale:
                raise ValidationError(self.env._(
                    'Unit %(unit)s must be offered for rent, for sale, or both.', unit=unit.display_name,
                ))
            if unit.is_for_rent and unit.yearly_rent <= 0:
                raise ValidationError(self.env._(
                    'The yearly rent is required for units offered for rent (%(unit)s).', unit=unit.display_name,
                ))
            if unit.is_for_sale and unit.sale_price <= 0:
                raise ValidationError(self.env._(
                    'The sale price is required for units offered for sale (%(unit)s).', unit=unit.display_name,
                ))

    @api.depends_context('lang')
    @api.depends('name', 'entity_id.code', 'state')
    def _compute_display_name(self):
        sold_label = self.env._('Sold')
        for unit in self:
            name = f'{unit.entity_id.code} / {unit.name}' if unit.entity_id.code else unit.name
            unit.display_name = f'{name} ({sold_label})' if unit.state == 'sold' else name


    def _aly_get_conflict(self, contract_type, date_start, date_end, exclude_contract=None):
        """Return a human message describing why the unit cannot be reserved or contracted
        for this period, or an empty string when it is free.

        Only the unit's committed status counts: approved contracts. Other reservations,
        whatever their state, never block (first approved contract wins)."""
        self.ensure_one()
        if contract_type == 'lease' and not self.is_for_rent:
            return self.env._('Unit %(unit)s is not offered for rent.', unit=self.display_name)
        if contract_type == 'sale' and not self.is_for_sale:
            return self.env._('Unit %(unit)s is not offered for sale.', unit=self.display_name)

        approved = self.contract_ids.filtered(lambda c: c.state == 'approved')
        if exclude_contract:
            approved -= exclude_contract
        sale = approved.filtered(lambda c: c.contract_type == 'sale')[:1]
        leases = approved.filtered(lambda c: c.contract_type == 'lease')

        if contract_type == 'sale':
            if sale:
                return self.env._(
                    'Unit %(unit)s is already sold (contract %(contract)s).',
                    unit=self.display_name, contract=sale.name,
                )
            blocking = leases.filtered(lambda c: c.date_end >= date_start)[:1]
            if blocking:
                return self.env._(
                    'Unit %(unit)s is leased until %(end)s (contract %(contract)s); it cannot be '
                    'handed over on %(date)s.',
                    unit=self.display_name, end=format_date(self.env, blocking.date_end), contract=blocking.name, date=format_date(self.env, date_start),
                )
            return ''

        if sale and date_end >= sale.date_start:
            return self.env._(
                'Unit %(unit)s is sold from %(date)s (contract %(contract)s).',
                unit=self.display_name, date=format_date(self.env, sale.date_start), contract=sale.name,
            )
        blocking = leases.filtered(lambda c: c.date_start <= date_end and date_start <= c.date_end)[:1]
        if blocking:
            return self.env._(
                'Unit %(unit)s is leased from %(start)s to %(end)s (contract %(contract)s), which '
                'overlaps the requested period.',
                unit=self.display_name, start=format_date(self.env, blocking.date_start), end=format_date(self.env, blocking.date_end), contract=blocking.name,
            )
        return ''

    def _aly_check_availability(self, contract_type, date_start, date_end, exclude_contract=None):
        conflict = self._aly_get_conflict(contract_type, date_start, date_end, exclude_contract)
        if conflict:
            raise ValidationError(conflict)

    @api.model
    def _cron_recompute_state(self):
        """The status depends on today's date, so it is refreshed every night."""
        units = self.with_context(active_test=False).search([])
        self.env.add_to_compute(self._fields['state'], units)
        units.flush_recordset(['state'])


    def action_reserve(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('New Reservation'),
            'res_model': 'aly.entity.reservation',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_unit_id': self.id,
                'default_contract_type': 'lease' if self.is_for_rent else 'sale',
            },
        }

    def action_view_reservations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aly_entity_management.aly_entity_reservation_action')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.id}
        return action

    def action_view_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aly_entity_management.aly_entity_contract_action')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'create': False}
        return action

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aly_entity_management.aly_entity_contract_invoice_action')
        action['domain'] = [('aly_contract_id.unit_id', '=', self.id)]
        action['context'] = {'create': False}
        return action

    def action_view_signatures(self):
        self.ensure_one()
        return self.env['aly.entity.contract']._aly_action_signatures([('unit_id', '=', self.id)])

    def action_view_payments(self):
        self.ensure_one()
        payments = self.contract_ids.invoice_ids.reconciled_payment_ids
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_account_payments')
        action['domain'] = [('id', 'in', payments.ids)]
        action['context'] = {'create': False}
        return action

    def action_view_maintenance(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'aly_entity_management.aly_entity_maintenance_request_action')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.id}
        return action

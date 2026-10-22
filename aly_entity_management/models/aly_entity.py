from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AlyEntity(models.Model):
    _name = 'aly.entity'
    _description = 'Real Estate Property'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(
        string='Property Name',
        required=True,
        tracking=True,
        index='trigram',
        help='Name the company uses for the property, e.g. "Al Nakheel Tower". Shown on '
             'units, reservations, contracts and invoices.',
    )
    code = fields.Char(
        string='Code',
        required=True,
        tracking=True,
        help='Short code of the property, unique within the company. Used to search '
             'quickly and printed next to the unit number on documents.',
    )
    entity_type = fields.Selection(
        selection=[
            ('tower', 'Tower'),
            ('compound', 'Residential Compound'),
            ('commercial', 'Commercial Building'),
            ('villas', 'Villas'),
        ],
        string='Property Type',
        required=True,
        default='tower',
        tracking=True,
        help='Kind of property. Used to group properties in lists and reports.',
    )
    street = fields.Char(
        string='Street',
        help='Street address of the property, printed on contracts.',
    )
    city = fields.Char(
        string='City',
        help='City of the property. Customers filter available units by city.',
    )
    country_id = fields.Many2one(
        comodel_name='res.country',
        string='Country',
        default=lambda self: self.env.company.country_id,
        ondelete='restrict',
        help='Country of the property, printed on contracts.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete='restrict',
        help='Company that owns and manages the property. Its units, reservations, '
             'contracts and invoices belong to this company, and users of other '
             'companies cannot see them.',
    )
    manager_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Property Manager',
        required=True,
        tracking=True,
        check_company=True,
        ondelete='restrict',
        help='Employee responsible for the property. Their user receives the reminders '
             'to send contract invoices and approves the maintenance hours, so the '
             'employee must be linked to a user.',
    )
    unit_ids = fields.One2many(
        comodel_name='aly.entity.unit',
        inverse_name='entity_id',
        string='Units',
        help='Residential and commercial units of this property.',
    )
    unit_count = fields.Integer(
        string='Units Count',
        compute='_compute_unit_counts',
        store=False,
        help='Total number of active units in the property.',
    )
    available_count = fields.Integer(
        string='Available Units',
        compute='_compute_unit_counts',
        store=False,
        help='Number of units that are free today.',
    )
    reserved_count = fields.Integer(
        string='Reserved Units',
        compute='_compute_unit_counts',
        store=False,
        help='Number of units with a confirmed reservation covering today.',
    )
    leased_count = fields.Integer(
        string='Leased Units',
        compute='_compute_unit_counts',
        store=False,
        help='Number of units with an approved lease contract covering today.',
    )
    sold_count = fields.Integer(
        string='Sold Units',
        compute='_compute_unit_counts',
        store=False,
        help='Number of units with an approved sale contract.',
    )
    reservation_count = fields.Integer(
        string='Reservation Count',
        compute='_compute_activity_counts',
        store=False,
        help='Number of reservations on the units of this property, all states included.',
    )
    contract_count = fields.Integer(
        string='Contract Count',
        compute='_compute_activity_counts',
        store=False,
        help='Number of lease and sale contracts on the units of this property, all states included.',
    )
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_activity_counts',
        store=False,
        help='Number of invoices generated from the contracts of this property.',
    )
    maintenance_count = fields.Integer(
        string='Maintenance Requests',
        compute='_compute_activity_counts',
        store=False,
        help='Number of maintenance requests on the units of this property, all states included.',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
        help='Archive the property instead of deleting it, so its history stays available.',
    )

    _sql_constraints = [
        ('code_company_uniq',
         'UNIQUE(code, company_id)',
         'The property code must be unique per company.'),
    ]

    @api.depends('unit_ids.state', 'unit_ids.active')
    def _compute_unit_counts(self):
        data = {
            (entity.id, state): count
            for entity, state, count in self.env['aly.entity.unit']._read_group(
                domain=[('entity_id', 'in', self.ids)],
                groupby=['entity_id', 'state'],
                aggregates=['__count'],
            )
        }
        for entity in self:
            counts = {state: data.get((entity.id, state), 0)
                      for state in ('available', 'reserved', 'leased', 'sold')}
            entity.available_count = counts['available']
            entity.reserved_count = counts['reserved']
            entity.leased_count = counts['leased']
            entity.sold_count = counts['sold']
            entity.unit_count = sum(counts.values())

    def _compute_activity_counts(self):
        def counts(model, field='entity_id'):
            return dict(self.env[model]._read_group(
                domain=[(field, 'in', self.ids)], groupby=[field], aggregates=['__count'],
            ))
        reservations = counts('aly.entity.reservation')
        contracts = counts('aly.entity.contract')
        invoices = {}
        for contract, count in self.env['account.move']._read_group(
                domain=[('aly_contract_id.entity_id', 'in', self.ids)],
                groupby=['aly_contract_id'], aggregates=['__count']):
            invoices[contract.entity_id] = invoices.get(contract.entity_id, 0) + count
        maintenance = counts('aly.entity.maintenance.request')
        for entity in self:
            entity.reservation_count = reservations.get(entity, 0)
            entity.contract_count = contracts.get(entity, 0)
            entity.invoice_count = invoices.get(entity, 0)
            entity.maintenance_count = maintenance.get(entity, 0)

    @api.constrains('manager_id')
    def _check_manager_has_user(self):
        for entity in self:
            if entity.manager_id and not entity.manager_id.user_id:
                raise ValidationError(self.env._(
                    'The employee %(employee)s has no user. Link a user to this employee '
                    'first, because reminders and approvals are sent to that user.',
                    employee=entity.manager_id.name,
                ))

    def _compute_display_name(self):
        for entity in self:
            entity.display_name = f'[{entity.code}] {entity.name}' if entity.code else entity.name

    def _aly_action_units(self, state=None):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aly_entity_management.aly_entity_unit_action')
        domain = [('entity_id', '=', self.id)]
        if state:
            domain.append(('state', '=', state))
        action['domain'] = domain
        action['context'] = {'default_entity_id': self.id}
        return action

    def _aly_action(self, xmlid, domain, context=None):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['domain'] = domain
        action['context'] = context or {'create': False}
        return action

    def action_view_reservations(self):
        return self._aly_action('aly_entity_management.aly_entity_reservation_action',
                                [('entity_id', '=', self.id)], {'search_default_filter_active': 1})

    def action_view_contracts(self):
        return self._aly_action('aly_entity_management.aly_entity_contract_action',
                                [('entity_id', '=', self.id)], {'create': False, 'search_default_filter_active': 1})

    def action_view_invoices(self):
        return self._aly_action('aly_entity_management.aly_entity_contract_invoice_action',
                                [('aly_contract_id.entity_id', '=', self.id)])

    def action_view_maintenance(self):
        return self._aly_action('aly_entity_management.aly_entity_maintenance_request_action',
                                [('entity_id', '=', self.id)], {})

    def action_view_units(self):
        self.ensure_one()
        return self._aly_action_units()

    def action_view_available_units(self):
        self.ensure_one()
        return self._aly_action_units('available')

    def action_view_reserved_units(self):
        self.ensure_one()
        return self._aly_action_units('reserved')

    def action_view_leased_units(self):
        self.ensure_one()
        return self._aly_action_units('leased')

    def action_view_sold_units(self):
        self.ensure_one()
        return self._aly_action_units('sold')

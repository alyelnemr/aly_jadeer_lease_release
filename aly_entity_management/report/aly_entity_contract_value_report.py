from odoo import fields, models, tools


class AlyEntityContractValueReport(models.Model):
    _name = 'aly.entity.contract.value.report'
    _description = 'Real Estate Contract Value Report'
    _auto = False
    _order = 'entity_id, unit_id'

    unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        readonly=True,
        ondelete='set null',
        help='Unit the row describes; the report has one row per active unit.',
    )
    entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        readonly=True,
        ondelete='set null',
        help='Property of the unit, used to group the values per tower, compound or building.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        readonly=True,
        ondelete='set null',
        help='Company that owns the unit; users only see the rows of their allowed companies.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        readonly=True,
        ondelete='set null',
        help='Currency of the amounts, taken from the company of the unit.',
    )
    unit_type = fields.Selection(
        selection=[
            ('residential', 'Residential'),
            ('commercial', 'Commercial'),
        ],
        string='Unit Type',
        readonly=True,
        help='Residential or commercial unit.',
    )
    state = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('reserved', 'Reserved'),
            ('leased', 'Leased'),
            ('sold', 'Sold'),
        ],
        string='Unit Status',
        readonly=True,
        help='Status of the unit today (available, reserved, leased or sold); it decides which value columns are filled.',
    )
    contract_id = fields.Many2one(
        comodel_name='aly.entity.contract',
        string='Contract',
        readonly=True,
        ondelete='set null',
        help='Contract the values come from: the running lease, the contract in progress '
             'of the reservation, or the sale contract. Empty for available units.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        readonly=True,
        ondelete='set null',
        help='Customer of that contract.',
    )
    contract_value = fields.Monetary(
        string='Contract Value',
        currency_field='currency_id',
        readonly=True,
        help='Leased: full value of the approved contract including fees. Reserved: value '
             'of the contract waiting for signature or approval (0 if not created yet). '
             'Sold: sale price. Available: none.',
    )
    annual_value = fields.Monetary(
        string='Annual Value',
        currency_field='currency_id',
        readonly=True,
        help='Value of one year, to compare all units fairly. Leased and reserved: yearly '
             'rent of the contract (or of the unit). Available: yearly rent entered on the '
             'unit, i.e. the potential value. Sold: none.',
    )
    potential_value = fields.Monetary(
        string='Potential Value',
        currency_field='currency_id',
        readonly=True,
        help='Yearly rent of the units that are available today: the income the company '
             'could still earn.',
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    u.id AS id,
                    u.id AS unit_id,
                    u.entity_id AS entity_id,
                    u.company_id AS company_id,
                    rc.currency_id AS currency_id,
                    u.unit_type AS unit_type,
                    u.state AS state,
                    COALESCE(lease.id, pending.id, sale.id) AS contract_id,
                    COALESCE(lease.partner_id, pending.partner_id, sale.partner_id, pending_res.partner_id) AS partner_id,
                    CASE u.state
                        WHEN 'leased' THEN lease.total_amount
                        WHEN 'reserved' THEN COALESCE(pending.total_amount, 0)
                        WHEN 'sold' THEN sale.base_amount
                        ELSE NULL
                    END AS contract_value,
                    CASE u.state
                        WHEN 'leased' THEN lease.yearly_rent
                        WHEN 'reserved' THEN COALESCE(NULLIF(pending.yearly_rent, 0), u.yearly_rent)
                        WHEN 'available' THEN u.yearly_rent
                        ELSE NULL
                    END AS annual_value,
                    CASE WHEN u.state = 'available' THEN u.yearly_rent ELSE NULL END AS potential_value
                FROM aly_entity_unit u
                JOIN res_company rc ON rc.id = u.company_id
                LEFT JOIN LATERAL (
                    SELECT c.id, c.partner_id, c.total_amount, c.yearly_rent
                    FROM aly_entity_contract c
                    WHERE c.unit_id = u.id AND c.state = 'approved' AND c.contract_type = 'lease'
                      AND c.date_start <= CURRENT_DATE AND c.date_end >= CURRENT_DATE
                    ORDER BY c.date_start DESC
                    LIMIT 1
                ) lease ON u.state = 'leased'
                LEFT JOIN LATERAL (
                    SELECT r.id, r.partner_id
                    FROM aly_entity_reservation r
                    WHERE r.unit_id = u.id AND r.state IN ('confirmed', 'awaiting_signature', 'signed')
                      AND (r.contract_type = 'sale' OR (r.date_start <= CURRENT_DATE AND r.date_end >= CURRENT_DATE))
                    ORDER BY r.date_start
                    LIMIT 1
                ) pending_res ON u.state = 'reserved'
                LEFT JOIN LATERAL (
                    SELECT c.id, c.partner_id, c.total_amount, c.yearly_rent
                    FROM aly_entity_contract c
                    WHERE c.reservation_id = pending_res.id AND c.state IN ('awaiting_signature', 'signed')
                    ORDER BY c.id DESC
                    LIMIT 1
                ) pending ON TRUE
                LEFT JOIN LATERAL (
                    SELECT c.id, c.partner_id, c.base_amount
                    FROM aly_entity_contract c
                    WHERE c.unit_id = u.id AND c.state = 'approved' AND c.contract_type = 'sale'
                    ORDER BY c.date_start DESC
                    LIMIT 1
                ) sale ON u.state = 'sold'
                WHERE u.active
            )
        """)

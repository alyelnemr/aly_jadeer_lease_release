from odoo import api, fields, models
from odoo.exceptions import AccessError

COMPANY_FIELDS = (
    'aly_reservation_validity_days', 'aly_invoice_reminder_days',
    'aly_default_service_fee', 'aly_default_admin_fee',
    'aly_rent_product_id', 'aly_sale_product_id',
    'aly_service_fee_product_id', 'aly_admin_fee_product_id',
)


class AlyEntitySettingsWizard(models.TransientModel):
    """Real estate settings of the current company, editable by real estate managers
    (the standard Settings screen is reserved to system administrators)."""
    _name = 'aly.entity.settings.wizard'
    _description = 'Real Estate Settings'

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        help='Company whose real estate settings are edited.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        help='Currency of the default fees.',
    )
    aly_reservation_validity_days = fields.Integer(
        string='Reservation Validity (Days)',
        help='Days a confirmed reservation waits for the customer signature before it expires.',
    )
    aly_invoice_reminder_days = fields.Integer(
        string='Invoice Reminder (Days Before)',
        help='Days before the planned send date when the property manager is reminded.',
    )
    aly_default_service_fee = fields.Monetary(
        string='Default Service Fee',
        currency_field='currency_id',
        help='Fixed service fee proposed on new contracts, billed on the first invoice.',
    )
    aly_default_admin_fee = fields.Monetary(
        string='Default Administrative Fee',
        currency_field='currency_id',
        help='Fixed administrative fee proposed on new contracts, billed on the first invoice.',
    )
    aly_rent_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Rent Product',
        ondelete='set null',
        help='Product of the rent lines of lease invoices.',
    )
    aly_sale_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Unit Sale Product',
        ondelete='set null',
        help='Product of the installment lines of sale invoices.',
    )
    aly_service_fee_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Service Fee Product',
        ondelete='set null',
        help='Product of the service fee line.',
    )
    aly_admin_fee_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Administrative Fee Product',
        ondelete='set null',
        help='Product of the administrative fee line.',
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        company = self.env.company
        for name in COMPANY_FIELDS:
            if name in fields_list:
                value = company[name]
                values[name] = value.id if isinstance(value, models.BaseModel) else value
        for kind in ('rent', 'sale', 'service_fee', 'admin_fee'):
            name = f'aly_{kind}_product_id'
            if name in fields_list and not values.get(name):
                values[name] = company._aly_get_product(kind).id
        return values

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('aly_entity_management.group_aly_entity_manager'):
            raise AccessError(self.env._('Only real estate managers can change these settings.'))
        values = {}
        for name in COMPANY_FIELDS:
            value = self[name]
            values[name] = value.id if isinstance(value, models.BaseModel) else value
        self.company_id.sudo().write(values)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': self.env._('Real estate settings saved.'),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

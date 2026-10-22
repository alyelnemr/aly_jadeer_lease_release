from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    aly_reservation_validity_days = fields.Integer(
        string='Reservation Validity (Days)',
        default=2,
        help='How many days a confirmed reservation stays valid while waiting for the '
             'customer to sign the contract. After that the daily job marks it as expired '
             'and frees the unit.',
    )
    aly_invoice_reminder_days = fields.Integer(
        string='Invoice Reminder (Days Before)',
        default=3,
        help='How many days before the planned send date of a contract invoice the '
             'property manager receives a reminder activity to confirm and send it.',
    )
    aly_default_service_fee = fields.Monetary(
        string='Default Service Fee',
        currency_field='currency_id',
        help='Fixed service fee proposed on every new contract. It is billed once, on the '
             'first invoice, and can be changed on the contract before it is sent.',
    )
    aly_default_admin_fee = fields.Monetary(
        string='Default Administrative Fee',
        currency_field='currency_id',
        help='Fixed administrative fee proposed on every new contract. It is billed once, '
             'on the first invoice, and can be changed on the contract before it is sent.',
    )
    aly_rent_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Rent Product',
        ondelete='restrict',
        help='Product used on the rent lines of lease invoices. Its income account and '
             'taxes decide how rent is booked.',
    )
    aly_sale_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Unit Sale Product',
        ondelete='restrict',
        help='Product used on the installment lines of sale invoices. Its income account '
             'and taxes decide how unit sales are booked.',
    )
    aly_service_fee_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Service Fee Product',
        ondelete='restrict',
        help='Product used on the service fee line of the first contract invoice.',
    )
    aly_admin_fee_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Administrative Fee Product',
        ondelete='restrict',
        help='Product used on the administrative fee line of the first contract invoice.',
    )

    _sql_constraints = [
        ('aly_reservation_validity_days_positive',
         'CHECK(aly_reservation_validity_days > 0)',
         'The reservation validity must be at least one day.'),
        ('aly_invoice_reminder_days_positive',
         'CHECK(aly_invoice_reminder_days >= 0)',
         'The invoice reminder days cannot be negative.'),
        ('aly_default_fees_positive',
         'CHECK(aly_default_service_fee >= 0 AND aly_default_admin_fee >= 0)',
         'The default fees cannot be negative.'),
    ]

    def _aly_get_product(self, kind):
        """Return the product configured for ``kind`` (rent, sale, service_fee, admin_fee),
        falling back to the product shipped with the module."""
        self.ensure_one()
        product = self[f'aly_{kind}_product_id']
        if not product:
            product = self.env.ref(f'aly_entity_management.product_aly_{kind}', raise_if_not_found=False)
        return product

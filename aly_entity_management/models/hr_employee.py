from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_maintenance_worker = fields.Boolean(
        string='Maintenance Worker',
        help='Check for employees who do maintenance work on leased and sold units. '
             'Only these employees can be chosen when real estate staff record '
             'maintenance hours on a contract.',
    )

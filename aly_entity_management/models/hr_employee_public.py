from odoo import fields, models


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    is_maintenance_worker = fields.Boolean(
        string='Maintenance Worker',
        readonly=True,
        help='Public copy of the employee flag, so staff without HR rights can pick '
             'maintenance workers when recording maintenance hours.',
    )

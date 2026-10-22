from odoo import fields, models


class AlyEntityUnitImage(models.Model):
    _name = 'aly.entity.unit.image'
    _description = 'Real Estate Unit Photo'
    _inherit = ['image.mixin']
    _order = 'sequence, id'

    name = fields.Char(
        string='Caption',
        required=True,
        help='Short caption shown under the photo, e.g. "Living room" or "Sea view".',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Order of the photo in the gallery; lower numbers are shown first.',
    )
    unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        required=True,
        index=True,
        ondelete='cascade',
        help='Unit the photo belongs to. The photo is deleted together with the unit.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='unit_id.company_id',
        store=True,
        help='Company of the unit, used by the multi-company access rule.',
    )

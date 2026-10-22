from odoo import models
from odoo.exceptions import UserError


class AlyEntityNavigationMixin(models.AbstractModel):
    """Smart buttons that open a linked record (contract, reservation, unit, property,
    customer). The button passes the Many2one field to follow in its context:
    ``context="{'aly_field': 'unit_id'}"``."""
    _name = 'aly.entity.navigation.mixin'
    _description = 'Real Estate Navigation Buttons'

    def action_aly_open_related(self):
        self.ensure_one()
        field_name = self.env.context.get('aly_field')
        field = self._fields.get(field_name)
        if not field or field.type != 'many2one':
            raise UserError(self.env._('This button is not linked to a related record.'))
        record = self[field_name]
        if not record:
            raise UserError(self.env._('There is no related record to open.'))
        action = {
            'type': 'ir.actions.act_window',
            'res_model': record._name,
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }
        if record._name == 'res.partner':
            action['views'] = [(self.env.ref('aly_entity_management.res_partner_view_form_aly_customer').id, 'form')]
        return action

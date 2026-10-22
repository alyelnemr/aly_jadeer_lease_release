from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

LATE_AFTER_DAYS = 7


class AlyEntityMaintenanceRequestLine(models.Model):
    _name = 'aly.entity.maintenance.request.line'
    _description = 'Maintenance Request Line'
    _order = 'date desc, time_from desc, id desc'
    _check_company_auto = True

    request_id = fields.Many2one(
        comodel_name='aly.entity.maintenance.request',
        string='Maintenance Request',
        required=True,
        index=True,
        ondelete='cascade',
        help='Request this visit belongs to. Its approval locks the visit.',
    )
    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Maintenance Worker',
        required=True,
        index=True,
        domain="[('is_maintenance_worker', '=', True)]",
        ondelete='restrict',
        help='Maintenance worker who did the work. Only employees flagged as maintenance '
             'workers can be chosen; real estate staff record visits on their behalf.',
    )
    date = fields.Date(
        string='Day Worked',
        required=True,
        default=fields.Date.context_today,
        help='Day the work was done. Cannot be in the future. A visit recorded more than '
             '7 days after this day is marked as late.',
    )
    time_from = fields.Float(
        string='From',
        required=True,
        help='Time the work started, e.g. 09:00.',
    )
    time_to = fields.Float(
        string='To',
        required=True,
        help='Time the work ended, e.g. 11:30. Must be after the start time on the same day; '
             'split work past midnight into two visits.',
    )
    hours = fields.Float(
        string='Hours Worked',
        compute='_compute_hours',
        store=True,
        help='Duration of the visit, computed from the start and end time.',
    )
    description = fields.Text(
        string='Description',
        required=True,
        help='What was done during the visit, e.g. "Replaced the AC drain pipe".',
    )
    contract_id = fields.Many2one(
        comodel_name='aly.entity.contract',
        string='Contract',
        related='request_id.contract_id',
        store=True,
        index=True,
        help='Contract the hours are recorded on, taken from the request.',
    )
    unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        related='request_id.unit_id',
        store=True,
        index=True,
        help='Unit where the work was done, taken from the request.',
    )
    entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        related='request_id.entity_id',
        store=True,
        index=True,
        help='Property of the unit, used to group the hours in reports.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='request_id.company_id',
        store=True,
        index=True,
        help='Company of the request, used by the multi-company access rule.',
    )
    state = fields.Selection(
        string='Request Status',
        related='request_id.state',
        store=True,
        help='Status of the request; the visit is locked once the request is sent for approval.',
    )
    recorded_on = fields.Datetime(
        string='Recorded On',
        related='create_date',
        help='Actual date and time the visit was first recorded in the system. It never changes, '
             'even when the visit is corrected.',
    )
    recorded_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Recorded By',
        related='create_uid',
        help='User who recorded the visit.',
    )
    is_late = fields.Boolean(
        string='Late',
        compute='_compute_late',
        store=True,
        help='The visit was recorded more than 7 days after the day worked.',
    )
    late_days = fields.Integer(
        string='Days Late',
        compute='_compute_late',
        store=True,
        help='Number of days between the day worked and the day the visit was recorded.',
    )

    @api.depends('time_from', 'time_to')
    def _compute_hours(self):
        for line in self:
            line.hours = max(line.time_to - line.time_from, 0.0)

    @api.depends('date', 'create_date')
    def _compute_late(self):
        for line in self:
            recorded = fields.Datetime.context_timestamp(line, line.create_date).date() if line.create_date \
                else fields.Date.context_today(line)
            days = (recorded - line.date).days if line.date else 0
            line.late_days = max(days, 0)
            line.is_late = days > LATE_AFTER_DAYS

    @api.constrains('time_from', 'time_to', 'date')
    def _check_times(self):
        today = fields.Date.context_today(self)
        for line in self:
            if not (0 <= line.time_from < 24 and 0 < line.time_to <= 24):
                raise ValidationError(self.env._('Times must be between 00:00 and 24:00.'))
            if line.time_to <= line.time_from:
                raise ValidationError(self.env._('The end time must be after the start time.'))
            if line.date and line.date > today:
                raise ValidationError(self.env._('The day worked cannot be in the future.'))

    @api.constrains('employee_id', 'date', 'time_from', 'time_to')
    def _check_overlap(self):
        for line in self:
            overlapping = self.search([
                ('id', '!=', line.id),
                ('employee_id', '=', line.employee_id.id),
                ('date', '=', line.date),
                ('time_from', '<', line.time_to),
                ('time_to', '>', line.time_from),
            ], limit=1)
            if overlapping:
                raise ValidationError(self.env._(
                    '%(worker)s already has a visit on %(date)s that overlaps these hours (%(other)s).',
                    worker=line.employee_id.name, date=line.date, other=overlapping.request_id.name,
                ))

    def _aly_check_editable(self, requests):
        if requests.filtered(lambda r: r.state != 'draft'):
            raise UserError(self.env._(
                'The visits of a maintenance request waiting for approval or approved cannot be changed.'
            ))

    @api.model_create_multi
    def create(self, vals_list):
        request_ids = [vals.get('request_id') for vals in vals_list if vals.get('request_id')]
        self._aly_check_editable(self.env['aly.entity.maintenance.request'].browse(request_ids))
        return super().create(vals_list)

    def write(self, vals):
        requests = self.request_id
        if vals.get('request_id'):
            requests |= self.env['aly.entity.maintenance.request'].browse(vals['request_id'])
        self._aly_check_editable(requests)
        return super().write(vals)

    def unlink(self):
        self._aly_check_editable(self.request_id)
        return super().unlink()

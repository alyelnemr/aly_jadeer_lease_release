from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

MAIL_FIELDS = {'message_main_attachment_id', 'activity_ids', 'message_follower_ids', 'message_ids'}


class AlyEntityMaintenanceRequest(models.Model):
    _name = 'aly.entity.maintenance.request'
    _description = 'Maintenance Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'aly.entity.navigation.mixin']
    _order = 'request_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='/',
        index='trigram',
        help='Unique reference given by the system when the request is created, e.g. MNT/2027/0001.',
    )
    title = fields.Char(
        string='Problem',
        required=True,
        tracking=True,
        help='Short description of the problem to fix, e.g. "Living room AC leak". One request '
             'per problem; a new problem is a new request.',
    )
    unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        required=True,
        tracking=True,
        index=True,
        ondelete='restrict',
        help='Unit where the maintenance is done. Its approved contract is proposed automatically.',
    )
    request_date = fields.Date(
        string='Request Date',
        required=True,
        tracking=True,
        default=fields.Date.context_today,
        help='Day the problem was reported. Used to find the contract running on the unit.',
    )
    contract_id = fields.Many2one(
        comodel_name='aly.entity.contract',
        string='Contract',
        compute='_compute_contract_id',
        store=True,
        precompute=True,
        readonly=False,
        required=True,
        tracking=True,
        index=True,
        check_company=True,
        domain="[('unit_id', '=', unit_id), ('state', '=', 'approved')]",
        ondelete='restrict',
        help='Approved lease or sale contract the maintenance hours are recorded on. Proposed from '
             'the unit and the request date; can be changed among the approved contracts of the unit.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        related='contract_id.partner_id',
        help='Tenant or buyer of the contract the maintenance is done for.',
    )
    entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        related='unit_id.entity_id',
        store=True,
        index=True,
        help='Property of the unit; its manager approves the request.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='unit_id.company_id',
        store=True,
        index=True,
        help='Company of the unit, used by the multi-company access rule.',
    )
    line_ids = fields.One2many(
        comodel_name='aly.entity.maintenance.request.line',
        inverse_name='request_id',
        string='Visits',
        copy=False,
        help='One line per visit of a maintenance worker: day, start and end time, and what was done.',
    )
    line_count = fields.Integer(
        string='Visits Count',
        compute='_compute_totals',
        store=True,
        help='Number of visits recorded on the request.',
    )
    total_hours = fields.Float(
        string='Total Hours',
        compute='_compute_totals',
        store=True,
        help='Sum of the hours worked on all the visits of the request.',
    )
    late_line_count = fields.Integer(
        string='Late Visits',
        compute='_compute_totals',
        store=True,
        help='Number of visits recorded more than 7 days after the day worked.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('to_approve', 'Waiting Approval'),
            ('approved', 'Approved'),
        ],
        string='Status',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
        index=True,
        help='Draft: visits are being recorded, or the request was sent back for correction. '
             'Waiting Approval: sent to the property manager, visits can no longer be changed. '
             'Approved: the request and all its visits are locked for everyone.',
    )
    approver_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Approver',
        related='entity_id.manager_id.user_id',
        help='User of the property manager, the only one who can approve the request.',
    )
    can_approve = fields.Boolean(
        string='Can Approve',
        compute='_compute_can_approve',
        store=False,
        help='Technical: the current user is the property manager of this request.',
    )
    approved_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Approved By',
        readonly=True,
        copy=False,
        ondelete='set null',
        help='Property manager who approved the request.',
    )
    approved_on = fields.Datetime(
        string='Approved On',
        readonly=True,
        copy=False,
        help='When the request was approved and locked.',
    )

    @api.depends('unit_id', 'request_date')
    def _compute_contract_id(self):
        for request in self:
            day = request.request_date or fields.Date.context_today(request)
            approved = request.unit_id.contract_ids.filtered(lambda c: c.state == 'approved')
            running = approved.filtered(
                lambda c: c.contract_type == 'sale' or (c.date_start <= day <= c.date_end)
            ).sorted('date_start', reverse=True)
            request.contract_id = running[:1] or approved.sorted('date_start', reverse=True)[:1]

    @api.depends('line_ids.hours', 'line_ids.is_late')
    def _compute_totals(self):
        for request in self:
            request.line_count = len(request.line_ids)
            request.total_hours = sum(request.line_ids.mapped('hours'))
            request.late_line_count = len(request.line_ids.filtered('is_late'))

    @api.depends_context('uid')
    @api.depends('approver_user_id')
    def _compute_can_approve(self):
        for request in self:
            request.can_approve = request.approver_user_id == self.env.user

    @api.constrains('unit_id', 'contract_id')
    def _check_contract_unit(self):
        for request in self:
            if request.contract_id.unit_id != request.unit_id:
                raise ValidationError(self.env._(
                    'The contract %(contract)s is not a contract of unit %(unit)s.',
                    contract=request.contract_id.name, unit=request.unit_id.display_name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('aly.entity.maintenance.request') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) - MAIL_FIELDS - {'state', 'approved_by_id', 'approved_on'} \
                and self.filtered(lambda r: r.state != 'draft'):
            raise UserError(self.env._(
                'A maintenance request waiting for approval or approved cannot be changed.'
            ))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.state != 'draft'):
            raise UserError(self.env._('Only draft maintenance requests can be deleted.'))
        return super().unlink()

    def action_submit(self):
        for request in self:
            if request.state != 'draft':
                raise UserError(self.env._('Only draft requests can be sent for approval.'))
            if not request.line_ids:
                raise UserError(self.env._('Add at least one visit before sending %(name)s for approval.',
                                           name=request.name))
            request.state = 'to_approve'
            if request.approver_user_id:
                request.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=self.env._('Maintenance request waiting for your approval'),
                    user_id=request.approver_user_id.id,
                )
        return True

    def _aly_check_approver(self):
        for request in self:
            if request.approver_user_id != self.env.user:
                raise AccessError(self.env._(
                    'Only the property manager (%(manager)s) can approve or send back this request.',
                    manager=request.approver_user_id.name or request.entity_id.manager_id.name,
                ))

    def action_approve(self):
        self._aly_check_approver()
        for request in self:
            if request.state != 'to_approve':
                raise UserError(self.env._('Only requests waiting for approval can be approved.'))
        self.activity_feedback(['mail.mail_activity_data_todo'])
        self.write({'state': 'approved', 'approved_by_id': self.env.user.id, 'approved_on': fields.Datetime.now()})
        return True

    def action_send_back(self):
        self.ensure_one()
        self._aly_check_approver()
        return self.env['aly.entity.cancel.wizard'].with_context(
            active_model=self._name, active_ids=self.ids, aly_send_back=True,
        )._aly_open()

    def _aly_send_back(self, reason):
        self._aly_check_approver()
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self.write({'state': 'draft'})
        for request in self:
            request.message_post(body=self.env._('Sent back for correction: %(reason)s', reason=reason))

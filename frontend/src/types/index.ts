/**
 * CampusConnect — Core TypeScript Types
 * Mirrors the backend domain models and API response shapes.
 * Keep in sync with backend Pydantic schemas.
 */

// ---------------------------------------------------------------------------
// Enums (must match backend exactly)
// ---------------------------------------------------------------------------
export type UserRole =
  | 'SYSTEM_ADMIN'
  | 'CLUB_SECRETARY'
  | 'FACULTY_ADVISOR'
  | 'HALL_INCHARGE'
  | 'ADVISOR_STUDENTS_UNION'
  | 'DEAN_STUDENT_AFFAIRS'
  | 'PRINCIPAL'
  | 'FINANCE_OFFICER'

export type ClubMemberRole = 'SECRETARY' | 'TREASURER' | 'MEMBER'

export type EventType =
  | 'CULTURAL'
  | 'TECHNICAL'
  | 'SPORTS'
  | 'WORKSHOP'
  | 'SEMINAR'
  | 'GUEST_LECTURE'
  | 'COMPETITION'
  | 'OUTREACH'
  | 'OTHER'

export type EventRequestStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'IN_REVIEW'
  | 'REVISION_REQUIRED'
  | 'APPROVED'
  | 'REJECTED'
  | 'CANCELLED'

export type EventStatus = 'SCHEDULED' | 'IN_PROGRESS' | 'ACTIVE' | 'COMPLETED' | 'CLOSURE_REQUESTED' | 'CLOSED' | 'CANCELLED' | 'ARCHIVED'

export type WorkflowStepStatus =
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'REVISION_REQUESTED'
  | 'SKIPPED'

export type NotificationType =
  | 'PROPOSAL_SUBMITTED'
  | 'APPROVAL_REQUIRED'
  | 'PROPOSAL_APPROVED'
  | 'PROPOSAL_REJECTED'
  | 'REVISION_REQUESTED'
  | 'HALL_CONFLICT'
  | 'FINANCE_VERIFICATION_REQUIRED'
  | 'BUDGET_VERIFIED'
  | 'BUDGET_QUERIED'
  | 'SYSTEM'

export type DocumentType =
  | 'EVENT_PLAN'
  | 'BUDGET_DETAILS'
  | 'AUTHORITY_LETTER'
  | 'CHIEF_GUEST_PROFILE'
  | 'VENUE_LAYOUT'
  | 'SUPPORTING'
  | 'POST_EVENT_PHOTO' | 'EXPENSE_INVOICE'
  | 'OTHER'

export type FinanceVerificationStatus = 'PENDING' | 'VERIFIED' | 'QUERIED'

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------
export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  email_verified: boolean
  department?: string
  designation?: string
  phone?: string
  last_login_at?: string
  created_at: string
}

export interface Club {
  id: string
  name: string
  slug: string
  description?: string
  faculty_advisor_id?: string
  faculty_advisor?: User
  academic_year: string
  is_active: boolean
  logo_url?: string
  member_count?: number
  created_at: string
}

export interface ClubMember {
  id: string
  club_id: string
  user_id: string
  user: User
  member_role: ClubMemberRole
  is_active: boolean
  joined_at: string
}

export interface Hall {
  id: string
  name: string
  location?: string
  capacity: number
  available_facilities: string[]
  is_active: boolean
  notes?: string
}

export interface VenueRequest {
  id: string
  hall_id: string
  hall?: Hall
  requested_date: string
  start_time: string
  end_time: string
  expected_audience?: number
  requires_stage: boolean
  requires_audio: boolean
  requires_lcd: boolean
  requires_ac: boolean
  requires_projector: boolean
  additional_requirements?: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED'
  rejection_reason?: string
}

export interface BudgetLineItem {
  id: string
  description: string
  category: string
  estimated_amount: number
  notes?: string
}

export interface BudgetProposal {
  id: string
  expected_income: number
  institute_contribution: number
  total_expected_expenditure: number
  notes?: string
  finance_status: FinanceVerificationStatus
  finance_notes?: string
  line_items: BudgetLineItem[]
}

export interface ResourceRequest {
  id: string
  resource_type: string
  quantity: number
  notes?: string
  status: 'PENDING' | 'CONFIRMED' | 'UNAVAILABLE'
}

export interface Document {
  id: string
  document_type: DocumentType
  original_filename: string
  file_size_bytes: number
  mime_type: string
  is_active: boolean
  uploaded_by: string
  uploader?: User
  created_at: string
}

export interface WorkflowInstanceStep {
  id: string
  step_order: number
  step_name: string
  assigned_to: string
  assignee?: User
  status: WorkflowStepStatus
  action_taken_at?: string
  comments?: string
  version_reviewed?: number
}

export interface WorkflowInstance {
  id: string
  current_step_order: number
  status: string
  version_number: number
  steps: WorkflowInstanceStep[]
}

export interface EventRequestVersion {
  id: string
  version_number: number
  submitted_at: string
  submitted_by: string
  submitter?: User
  change_summary?: string
}

export interface EventRequest {
  id: string
  club_id: string
  club?: Club
  submitted_by: string
  submitted_by_user?: User
  title: string
  description?: string
  event_type: EventType
  expected_attendees?: number
  event_date?: string
  chief_guest_name?: string
  chief_guest_designation?: string
  chief_guest_institution?: string
  status: EventRequestStatus
  current_version: number
  academic_year: string
  venue_request?: VenueRequest
  budget_proposal?: BudgetProposal
  resource_requests: ResourceRequest[]
  documents: Document[]
  workflow_instance?: WorkflowInstance
  versions: EventRequestVersion[]
  created_at: string
  updated_at: string
}

export interface Event {
  id: string
  event_request_id: string
  club_id: string
  club?: Club
  hall_id?: string
  hall?: Hall
  title: string
  description?: string
  event_type: EventType
  event_date: string
  start_time: string
  end_time: string
  expected_attendees?: number
  status: EventStatus
  academic_year: string
  created_at: string
}

export interface Notification {
  id: string
  notification_type: NotificationType
  title: string
  message: string
  is_read: boolean
  read_at?: string
  event_request_id?: string
  event_request?: Pick<EventRequest, 'id' | 'title' | 'status'>
  created_at: string
}

export interface AuditLogEntry {
  id: string
  actor_email?: string
  actor_role?: string
  action: string
  entity_type: string
  entity_id?: string
  previous_state?: Record<string, unknown>
  new_state?: Record<string, unknown>
  reason?: string
  ip_address?: string
  created_at: string
}

// ---------------------------------------------------------------------------
// API Response wrappers
// ---------------------------------------------------------------------------
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface ApiError {
  error: string
  message: string
  detail?: unknown
}

// ---------------------------------------------------------------------------
// Auth types
// ---------------------------------------------------------------------------
export interface AuthTokens {
  access_token: string
  token_type: 'bearer'
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  full_name: string
  password: string
  role?: UserRole
}

// ---------------------------------------------------------------------------
// Dashboard types
// ---------------------------------------------------------------------------
export interface DashboardSummary {
  role: UserRole
  stats: Record<string, number>
  pending_actions: number
  recent_activity: AuditLogEntry[]
}


export type PostEventReportStatus = 'DRAFT' | 'SUBMITTED' | 'REVISION_REQUIRED' | 'CERTIFIED'

export interface PostEventReport {
  id: string
  event_id: string
  revision_number: number
  actual_attendance: number
  summary: string
  objectives_achieved: string
  outcomes?: string | null
  challenges?: string | null
  status: PostEventReportStatus
  submitted_by: string
  submitted_at: string
  certified_by?: string | null
  certified_at?: string | null
  certification_remarks?: string | null
  created_at: string
  updated_at: string
}

export interface PostEventReportCreate {
  actual_attendance: number
  summary: string
  objectives_achieved: string
  outcomes?: string
  challenges?: string
}

export interface PostEventReportUpdate {
  actual_attendance?: number
  summary?: string
  objectives_achieved?: string
  outcomes?: string
  challenges?: string
}

export interface PostEventReportCertify {
  remarks?: string
}

export interface PostEventReportRevisionRequest {
  remarks: string
}

export interface ConfirmedEvent {
  id: string
  event_request_id: string
  title: string
  description?: string | null
  event_type: EventType
  event_date: string
  start_time: string
  end_time: string
  expected_attendees?: number | null
  status: EventStatus
  club_id: string
  hall_id?: string | null
  post_event_report?: PostEventReport | null
  created_at: string
}

export interface EvidenceDocument {
  id: string
  event_id: string
  uploaded_by: string
  document_type: DocumentType
  original_filename: string
  mime_type: string
  file_size_bytes: number
  geo_latitude?: number | null
  geo_longitude?: number | null
  geo_source?: string | null
  created_at: string
}


// ============================================================================
// ACTUAL EXPENSES & BILLS (PHASE 2.2)
// ============================================================================

export type BudgetLineItemCategory =
  | 'MATERIALS'
  | 'TRAVEL'
  | 'PRINTING'
  | 'FOOD'
  | 'EQUIPMENT'
  | 'OTHER'

export type ActualExpenseStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'VERIFIED'
  | 'PARTIALLY_VERIFIED'
  | 'QUERIED'
  | 'DISALLOWED'

export interface ActualExpense {
  id: string
  event_id: string
  budget_line_item_id?: string | null
  category: BudgetLineItemCategory
  description: string
  vendor_name: string
  vendor_gstin?: string | null
  invoice_number?: string | null
  invoice_date: string
  claimed_amount: string
  verified_amount?: string | null
  disallowed_amount: string
  status: ActualExpenseStatus
  bill_document_id: string
  submitted_by: string
  submitted_by_name?: string | null
  submitted_by_email?: string | null
  submitted_at?: string | null
  verified_by?: string | null
  verified_by_name?: string | null
  verified_by_email?: string | null
  verified_at?: string | null
  finance_remarks?: string | null
  query_reason?: string | null
  is_flagged_for_review: boolean
  review_notes?: string | null
  bill_original_filename?: string | null
  created_at: string
  updated_at: string
}

export interface ExpenseCategorySummary {
  category: string
  claimed_amount: string
  verified_amount: string
  disallowed_amount: string
  count: number
}

export interface ExpenseLedgerSummary {
  event_id: string
  sanctioned_budget: string
  total_claimed_spend: string
  total_verified_spend: string
  total_disallowed_spend: string
  total_expenses_count: number
  status_counts: Record<string, number>
  category_breakdown: ExpenseCategorySummary[]
  can_submit: boolean
  can_audit: boolean
  delivery_certified: boolean
  items: ActualExpense[]
}

export interface ActualExpenseCreate {
  category: BudgetLineItemCategory
  description: string
  vendor_name: string
  vendor_gstin?: string | null
  invoice_number?: string | null
  invoice_date: string
  claimed_amount: number | string
  bill_document_id: string
  budget_line_item_id?: string | null
}

export interface ActualExpenseUpdate {
  category?: BudgetLineItemCategory
  description?: string
  vendor_name?: string
  vendor_gstin?: string | null
  invoice_number?: string | null
  invoice_date?: string | null
  claimed_amount?: number | string
  bill_document_id?: string
  budget_line_item_id?: string | null
}

export interface BillUploadResponse {
  id: string
  original_filename: string
  file_size_bytes: number
  mime_type: string
  file_hash?: string | null
  created_at: string
}

// ============================================================================
// FINANCIAL SETTLEMENT, CASH ADVANCE, & ACTUAL INCOME (PHASE 2.3)
// ============================================================================

export type CashAdvanceStatus = 'REQUESTED' | 'APPROVED' | 'DISBURSED' | 'REJECTED'

export type IncomeSourceType =
  | 'REGISTRATION_FEE'
  | 'SPONSORSHIP'
  | 'STALL_RENTAL'
  | 'TICKET_SALES'
  | 'DONATION'
  | 'OTHER'

export type ActualIncomeStatus = 'RECORDED' | 'VERIFIED' | 'REJECTED'

export type SettlementStatus =
  | 'DRAFT'
  | 'UNDER_AUDIT'
  | 'APPROVED'
  | 'QUERIED'
  | 'PENDING_REIMBURSEMENT'
  | 'PENDING_REFUND'
  | 'SETTLED'
  | 'REOPENED'

export type SettlementType = 'REIMBURSEMENT_DUE' | 'REFUND_DUE' | 'BALANCED'

export type SettlementPaymentType =
  | 'REIMBURSEMENT_DISBURSEMENT'
  | 'ADVANCE_REFUND_RECEIPT'

export type PaymentMethod =
  | 'BANK_TRANSFER_NEFT'
  | 'CHEQUE'
  | 'CASH_VOUCHER'
  | 'INSTITUTIONAL_TRANSFER'

export interface CashAdvance {
  id: string
  event_id: string
  recipient_id: string
  amount_requested: string
  amount_approved?: string | null
  amount_disbursed: string
  status: CashAdvanceStatus
  notes?: string | null
  rejection_reason?: string | null
  approved_by?: string | null
  disbursed_by?: string | null
  disbursement_date?: string | null
  payment_reference?: string | null
  created_at: string
  updated_at: string
}

export interface CashAdvanceRequestCreate {
  amount_requested: number | string
  reason: string
}

export interface CashAdvanceApprove {
  amount_approved: number | string
  remarks?: string
}

export interface CashAdvanceReject {
  rejection_reason: string
}

export interface CashAdvanceDisburse {
  amount_disbursed: number | string
  payment_reference: string
  disbursement_date?: string
  notes?: string
}

export interface ActualIncome {
  id: string
  event_id: string
  source_type: IncomeSourceType
  description: string
  payer_name: string
  amount: string
  received_date: string
  reference_number?: string | null
  evidence_document_id: string
  status: ActualIncomeStatus
  recorded_by: string
  verified_by?: string | null
  verified_at?: string | null
  finance_remarks?: string | null
  created_at: string
  updated_at: string
}

export interface ActualIncomeCreate {
  source_type: IncomeSourceType
  amount: number | string
  description: string
  payer_name: string
  received_date: string
  evidence_document_id: string
  reference_number?: string
}

export interface ActualIncomeVerify {
  finance_remarks?: string
}

export interface ActualIncomeReject {
  rejection_reason: string
  finance_remarks?: string
}

export interface SettlementPayment {
  id: string
  settlement_id: string
  payment_type: SettlementPaymentType
  amount: string
  payment_method: PaymentMethod
  transaction_reference: string
  transaction_date: string
  proof_document_id: string
  recorded_by: string
  notes?: string | null
  created_at: string
}

export interface SettlementPaymentCreate {
  payment_type: SettlementPaymentType
  amount: number | string
  payment_method: PaymentMethod
  transaction_reference: string
  transaction_date: string
  proof_document_id: string
  notes?: string
}

export interface SettlementRevision {
  id: string
  settlement_id: string
  revision_number: number
  snapshot_data: Record<string, unknown>
  reopened_by: string
  reopening_reason: string
  created_at: string
}

export interface FinancialSettlement {
  id: string
  event_id: string
  approved_version_id: string
  sanctioned_grant: string
  sanctioned_expenditure: string
  expected_income: string
  total_claimed_expenditure: string
  total_verified_expenditure: string
  total_disallowed_expenditure: string
  total_verified_income: string
  net_deficit: string
  institutional_payout: string
  cash_advance_disbursed: string
  settlement_balance: string
  reimbursement_due: string
  refund_due: string
  settlement_type: SettlementType
  status: SettlementStatus
  prepared_by: string
  submitted_at?: string | null
  audited_by?: string | null
  audited_at?: string | null
  finance_remarks?: string | null
  query_reason?: string | null
  created_at: string
  updated_at: string
}

export interface FinancialSettlementDetail extends FinancialSettlement {
  payments: SettlementPayment[]
  revisions: SettlementRevision[]
}

export interface SettlementAuditRequest {
  action: 'APPROVE' | 'QUERY'
  remarks?: string
  query_reason?: string
}

export interface SettlementReopenRequest {
  reopening_reason: string
}

export interface ClosureEligibility {
  eligible: boolean
  blockers: string[]
  event_id: string
  settlement_id?: string | null
}

export interface EvidenceUploadResponse {
  document_id: string
  filename: string
  file_size: number
  content_type: string
  document_type: DocumentType
  uploaded_at: string
}

// ============================================================================
// EVENT CLOSEOUT, REOPENING & ARCHIVAL (PHASE 2.4)
// ============================================================================

export interface VenueStatusInfo {
  has_booking: boolean
  booking_ended: boolean
  hall_id?: string | null
}

export interface CloseoutEligibilityInfo {
  eligible: boolean
  blockers: string[]
  warnings: string[]
  event_status: string
  settlement_status?: string | null
  report_status?: string | null
  venue_status: VenueStatusInfo
  event_id: string
  settlement_id?: string | null
  report_id?: string | null
}

export interface LatestClosureRequestInfo {
  requested_by?: string | null
  requested_at?: string | null
  remarks?: string | null
}

export interface EventClosureResponse {
  id: string
  event_id: string
  settlement_id: string
  post_event_report_id: string
  requested_by?: string | null
  requested_at?: string | null
  certified_by: string
  certified_at: string
  closure_notes?: string | null
  venue_cleared: boolean
  certificate_manifest_hash: string
  created_at: string
  updated_at: string
}

export interface EventClosureRevisionResponse {
  id: string
  event_id: string
  closure_id: string
  revision_number: number
  reopened_by: string
  reopened_at: string
  reopening_reason: string
  snapshot_data: Record<string, unknown>
  created_at: string
}

export interface EventCloseoutActionResponse {
  event_id: string
  status: EventStatus
  message: string
}

export interface EventClosureDetailResponse {
  event_id: string
  event_status: EventStatus
  is_archived: boolean
  eligibility: CloseoutEligibilityInfo
  closure?: EventClosureResponse | null
  revisions: EventClosureRevisionResponse[]
  latest_request?: LatestClosureRequestInfo | null
}

export interface EventCloseoutRequestCreate {
  remarks?: string | null
}

export interface EventCloseoutCertifyRequest {
  venue_cleared: boolean
  closure_notes?: string | null
}

export interface EventCloseoutRejectRequest {
  reason: string
}

export interface EventReopenRequestCreate {
  reason: string
}

export interface EventReopenApproveRequest {
  reason: string
}

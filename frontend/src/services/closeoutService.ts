/**
 * CampusConnect - Event Closeout API Service (Phase 2.4)
 * Provides typed wrappers for the 7 event closeout, reopening, and archival endpoints.
 * Backend remains authoritative for all authorization and lifecycle rules.
 */

import { apiClient } from '@/lib/apiClient'
import type {
  EventClosureDetailResponse,
  EventCloseoutActionResponse,
  EventCloseoutRequestCreate,
  EventCloseoutCertifyRequest,
  EventCloseoutRejectRequest,
  EventReopenRequestCreate,
  EventReopenApproveRequest,
} from '@/types'

/**
 * 1. Fetch comprehensive closeout state, eligibility, active closure, and history.
 */
export async function getCloseoutDetails(eventId: string): Promise<EventClosureDetailResponse> {
  const response = await apiClient.get<EventClosureDetailResponse>(`/events/${eventId}/closure`)
  return response.data
}

/**
 * 2. Club Secretary submits formal petition for institutional closeout.
 */
export async function requestCloseout(
  eventId: string,
  payload?: EventCloseoutRequestCreate
): Promise<EventCloseoutActionResponse> {
  const response = await apiClient.post<EventCloseoutActionResponse>(
    `/events/${eventId}/closure/request`,
    payload || {}
  )
  return response.data
}

/**
 * 3. Dean, Principal, or authorized Advisor certifies closeout with venue clearance attestation.
 */
export async function certifyCloseout(
  eventId: string,
  payload: EventCloseoutCertifyRequest
): Promise<EventCloseoutActionResponse> {
  const response = await apiClient.post<EventCloseoutActionResponse>(
    `/events/${eventId}/closure/certify`,
    payload
  )
  return response.data
}

/**
 * 4. Institutional authority rejects closeout request with mandatory justification.
 */
export async function rejectCloseout(
  eventId: string,
  payload: EventCloseoutRejectRequest
): Promise<EventCloseoutActionResponse> {
  const response = await apiClient.post<EventCloseoutActionResponse>(
    `/events/${eventId}/closure/reject`,
    payload
  )
  return response.data
}

/**
 * 5. Secretary, Advisor, or Finance Officer petitions to reopen a closed event.
 */
export async function requestReopen(
  eventId: string,
  payload: EventReopenRequestCreate
): Promise<EventCloseoutActionResponse> {
  const response = await apiClient.post<EventCloseoutActionResponse>(
    `/events/${eventId}/closure/reopen-request`,
    payload
  )
  return response.data
}

/**
 * 6. Dean or Principal approves event reopening with statutory justification.
 */
export async function approveReopen(
  eventId: string,
  payload: EventReopenApproveRequest
): Promise<EventCloseoutActionResponse> {
  const response = await apiClient.post<EventCloseoutActionResponse>(
    `/events/${eventId}/closure/reopen-approve`,
    payload
  )
  return response.data
}

/**
 * 7. System Admin moves closed event to permanent immutable archive.
 */
export async function archiveEvent(eventId: string): Promise<EventCloseoutActionResponse> {
  const response = await apiClient.post<EventCloseoutActionResponse>(`/events/${eventId}/archive`, {})
  return response.data
}

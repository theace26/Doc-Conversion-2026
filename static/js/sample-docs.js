/* Sample doc records for dev-chrome smoke testing.
 * Twelve realistic IBEW Local 46 documents covering all eight formats.
 * Plan 3 replaces this with real /api/search results.
 */
(function (global) {
  'use strict';

  var SAMPLE_DOCS = [
    {
      id: 'd1', format: 'pdf',
      title: 'Q4 2025 Financial Summary',
      snippet: 'Revenue increased 18% year over year, driven primarily by member dues growth and the new training-fund distributions approved in March.',
      path: '/finance/2025/q4/Q4-financials.pdf',
      size: 3355443, modified: '2026-04-28T14:08:00Z', favorite: true
    },
    {
      id: 'd2', format: 'docx',
      title: 'Contract Negotiation Prep v3',
      snippet: 'Opening positions for the May 2026 cycle. Priority items: wage scale adjustment, healthcare contribution cap, apprentice ratio.',
      path: '/local-46/contracts/contract-prep-v3.docx',
      size: 901120, modified: '2026-04-28T14:00:00Z'
    },
    {
      id: 'd3', format: 'pptx',
      title: 'Member Orientation 2026',
      snippet: 'Welcome to IBEW Local 46. Benefits enrollment, dues schedule, training pathways, first-year apprentice timeline.',
      path: '/training/onboard/orientation-2026.pptx',
      size: 14680064, modified: '2026-04-28T13:54:00Z'
    },
    {
      id: 'd4', format: 'xlsx',
      title: 'Apprentice Hours Tracking',
      snippet: 'FY2026 cohort progress as of period 4. 18 apprentices on track, 3 flagged for OJT shortfall, 1 on probation pending steward review.',
      path: '/training/tracking/apprentice-hours.xlsx',
      size: 1153434, modified: '2026-04-28T13:46:00Z'
    },
    {
      id: 'd5', format: 'eml',
      title: 'Re: Jurisdiction dispute',
      snippet: 'From Local 76 BA: regarding the Mercer Island substation work, our position remains that fiber pulls within the control building fall under our agreement.',
      path: '/correspondence/2026-q1/jurisdiction-thread.eml',
      size: 145408, modified: '2026-04-28T13:30:00Z'
    },
    {
      id: 'd6', format: 'md',
      title: '# Bylaws Revision Draft',
      snippet: 'Section 4 amendments for the May general meeting vote. Delegate selection, executive board terms, finance-review committee scope.',
      path: '/governance/bylaws/bylaws-revision-draft.md',
      size: 28672, modified: '2026-04-28T13:08:00Z'
    },
    {
      id: 'd7', format: 'psd',
      title: 'Brand Refresh Assets',
      snippet: 'Layered source for member portal redesign. Includes typography, color palette, logo lockups, business-card treatments.',
      path: '/design/2026-refresh/brand-refresh.psd',
      size: 87654321, modified: '2026-04-28T12:08:00Z'
    },
    {
      id: 'd8', format: 'mp4',
      title: 'JATC Welcome Video',
      snippet: 'Transcribed and indexed. Covers training milestones, classroom expectations, and union history. 14:22 runtime, 1080p.',
      path: '/training/media/jatc-welcome.mp4',
      size: 587202560, modified: '2026-04-28T11:08:00Z'
    },
    {
      id: 'd9', format: 'pdf',
      title: 'Safety Bulletin Q1',
      snippet: 'Updated arc-flash PPE requirements per OSHA 1910 revisions. Effective immediately for all energized work above 240V.',
      path: '/safety/bulletins/safety-q1.pdf',
      size: 2516582, modified: '2026-04-28T10:08:00Z'
    },
    {
      id: 'd10', format: 'xlsx',
      title: 'Pension Allocation 2026',
      snippet: 'Q1 distribution table with member-by-member breakdown. Includes vesting status, contribution year, projected payout at retirement age.',
      path: '/finance/pension/pension-2026.xlsx',
      size: 4194304, modified: '2026-04-28T09:08:00Z'
    },
    {
      id: 'd11', format: 'docx',
      title: 'Steward Training Notes',
      snippet: 'Consolidated from three sessions. Grievance handling, escalation paths, member-rights primer, common contract-language traps.',
      path: '/training/stewards/steward-notes.docx',
      size: 327680, modified: '2026-04-28T08:08:00Z'
    },
    {
      id: 'd12', format: 'eml',
      title: 'Re: Apprentice probation',
      snippet: 'Following up on the steward review — recommend extending the period by 30 days with weekly check-ins. Coordinate with JATC.',
      path: '/correspondence/2026-q1/probation-thread.eml',
      size: 98304, modified: '2026-04-28T07:08:00Z'
    }
  ];

  global.MFSampleDocs = SAMPLE_DOCS;
})(window);

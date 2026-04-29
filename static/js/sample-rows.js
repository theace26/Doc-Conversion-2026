/* Sample browse-row data for the v1 Search-home page.
 * Plan 4 will replace these with live API calls. */
(function (global) {
  'use strict';

  global.MFSampleRows = {
    pinnedFolders: [
      { id: 'p1', path: '/local-46/contracts',     count: 428,   meta: '3 added today' },
      { id: 'p2', path: '/training/curriculum',    count: 1206,  meta: 'updated 2 days ago' },
      { id: 'p3', path: '/finance/2025',           count: 847,   meta: 'updated this week' },
      { id: 'p4', path: '/governance/bylaws',      count: 62,    meta: 'revision in progress' },
    ],

    fromWatchedFolders: window.MFSampleDocs ? window.MFSampleDocs.slice(0, 6) : [],

    mostAccessedThisWeek: window.MFSampleDocs ? window.MFSampleDocs.slice(0, 6).map(function (d, i) {
      return Object.assign({}, d, { opens: 42 - i * 4 });
    }) : [],

    flaggedForReview: window.MFSampleDocs ? window.MFSampleDocs.slice(0, 3).map(function (d) {
      return Object.assign({}, d, {
        snippet: 'AI flagged: ' + (d.snippet || '').slice(0, 80),
      });
    }) : [],

    topics: [
      { name: 'Contracts',           count: 428 },
      { name: 'Safety bulletins',    count: 312 },
      { name: 'Training materials',  count: 1206 },
      { name: 'Financial reports',   count: 847 },
      { name: 'Correspondence',      count: 2140 },
      { name: 'Bylaws & governance', count: 62 },
      { name: 'Member records',      count: 4820 },
      { name: 'Apprentice',          count: 1890 },
      { name: 'Pension & benefits',  count: 340 },
      { name: 'Jurisdiction',        count: 156 },
    ],

    recentSearches: [
      'arc-flash PPE requirements',
      'jurisdiction Local 76',
      'apprentice OJT shortfall',
      'master agreement section 12',
      'healthcare contribution cap',
      'steward training grievance',
      'pension allocation 2026',
      'bylaws delegate selection',
    ],
  };
})(window);

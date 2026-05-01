// Excluded RSID Clean Names
// These report suites will always be filtered out from botInvestigation and botValidation lists
// regardless of their visit counts

const excludedRsidCleanNames = [
    'AdobeUsageAnalytics',
    'SquadIntel',
    'WebSDKTest',
    'AAConnector',
    'GLOBALDEVELOPMENTREPORTSUITE'
];

module.exports = excludedRsidCleanNames;
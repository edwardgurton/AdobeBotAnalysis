//Step Six: Create a report request config using the other dimension (the one with more elements) and any metrics you need

requestName = 'LegendFinalBotMetricsDevelopmentIncludeByYear' // This is the name of the report request

// With metrics
// const metrics = [
//   { metricId: 'cm3938_67877f0e25c74e65d1f3f449', metricName: 'raw_clickouts_linear_7d' },
//   { metricId: 'cm3938_68655d7318c56ac719c11a44', metricName: 'raw_clickouts_participation_7d' },
//   { metricId: 'cm3938_68655dd05c74c471e8de44d0', metricName: 'unique_visit_clickouts_linear_7d' },
//   { metricId: 'cm3938_68655e0b18c56ac719c11a47', metricName: 'unique_visit_clickouts_participation_7d' },
//   { metricId: 'metrics/amo_cost', metricName: 'adobe_advertising_cost'},
//   { metricId: 'metrics/amo_clicks', metricName: 'adobe_advertising_clicks'},
//   { metricId: 'metrics/amo_impressions', metricName: 'adobe_advertising_impressions'}
// ];

const metrics = []

clientName = 'Legend'
dimension = 'variables/daterangeyear'

//Add segments in the array with comma separation
//Add master bot segment for Legend
//Add Regions = USA and Canada to limit data in this report
//masterBotSegment = 's3938_686797a0feff97c4e3c747c9' // Master Bot Filter EXCLUDE
masterBotSegmentCurrentInclude = 's3938_6892257b8fb8265765efa206'
//usaCanadaOnlySegment = 's3938_681e521d16e3be6770921fa8' // USA and Canada Only Segment

segments = [masterBotSegmentCurrentInclude] // Master Bot Filter EXCLUDE

const addRequestDetails = require('../utils/addRequestDetails');
addRequestDetails(clientName, requestName, dimension, segments, null, metrics)


//Step Seven: Run a test report to ensure that the request is valid
const downloadAdobeTable = require('../downloadAdobeTable');
requestName = 'BotInvestigationUnfilteredMetricsByRegion'
reportFromDate = '2025-07-01'
reportToDate = '2025-07-02'
clientName = 'Legend'

additionalSegment = undefined

retrieveLegendRsid = require('../utils/retrieveLegendRsid');
suite = 'Casinoorg'
rsid = retrieveLegendRsid(suite)
console.log(rsid)

downloadAdobeTable(reportFromDate, reportToDate, requestName, clientName, additionalSegment, rsid)
setTimeout(() => {
    process.exit(0);
// This is a workaround to ensure that the downloadAdobeTable exits after completion. Large requests may take up tp 5 minutes (300000 ms) to complete.
}, 60000);


//Test transform of file

const processJSONFiles = require('../processJSONFiles');
const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath');
const folderPath = getJsonStorageFolderPath('Legend');
const filePattern = /Legend_BotInvestigationUnfilteredMetricsByRegion_2025-07-01_2025-07-02.json$/;
const optionalFolder = 'TestTransform'; // Optional subdirectory within the CSV folder
processJSONFiles(folderPath, filePattern, optionalFolder)



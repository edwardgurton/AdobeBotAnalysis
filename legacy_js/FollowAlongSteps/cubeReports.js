//This is a guide for running a "cube report". I.e. 3 dimensions. You need this for when Data Warehouse can't service a request as you require either a complex segment or a calculated metric.

//Steps One to Four may be skipped if you are using metrics with non default attribution.
// If you have a metric with non default attribution, you need to decide which dimension will need to be last touch, and which will actually be attributed in the non-default way.
// The last touch dimension will be the one that is used in the segments.
// For example, lets say you want to combine marketing channels and georegion. 
// In this scenario, you would probably want the marketing channel dimension in the reports and use region
// Otherwise, you end up attributing the metrics per region, with 

//Step One: Create Request Details for each dimension
// a) Use addRequestDetails.js with each dimension

const addRequestDetails = require('../utils/addRequestDetails');

clientName = 'Legend'
// Hint: Many dimension names are stored in usefulInfo
dimension1 = 'variables/marketingchannel.marketing-channel-attribution'
report1RequestName = 'LegendMarketingChannelSegments'

dimension2 = 'variables/georegion'
report2RequestName = 'LegendGeoRegionSegments'

// If you want to add a segment (e.g. the Legend master bot filter) then add it here
masterBotSegment = 's3938_61bb0165a88ab931afa78e4c' // Master Bot Filter EXCLUDE

// Note: addRequestDetails(clientName, requestName, dimension, segments, rowLimit, metrics)
addRequestDetails(clientName, report1RequestName, dimension1, [masterBotSegment])
addRequestDetails(clientName, report2RequestName, dimension2, [masterBotSegment])

//Step Two: Download Each Report

downloadAdobeTable = require('../downloadAdobeTable');


reportFromDate = '2023-07-01'
reportToDate = '2025-06-30'
//requestNames = copy from step one
report1RequestName = 'LegendMarketingChannelSegments'
report2RequestName = 'LegendGeoRegionSegments'
reportClientName = 'Legend'
//You can add another segment@: Add a note here to remind yourself why you added this segment >>
additionalSegment = 's3938_681e521d16e3be6770921fa8'
//add the RSID
//special code for Legend
retrieveLegendRsid = require('../utils/retrieveLegendRsid');
suite = 'Casinoorg'
rsid = retrieveLegendRsid(suite)
console.log(rsid)
// rsid = 

downloadAdobeTable(reportFromDate,reportToDate,report1RequestName,reportClientName,additionalSegment,rsid)
downloadAdobeTable(reportFromDate,reportToDate,report2RequestName,reportClientName,additionalSegment,rsid)
setTimeout(() => {
    process.exit(0);
// This is a workaround to ensure that the downloadAdobeTable exits after completion. Large requests may take up tp 5 minutes (300000 ms) to complete.
}, 120000);

//Step Three: Process JSON files that you downloaded into CSV files

const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath');

clientName = 'Legend'
folderPath = getJsonStorageFolderPath(clientName)

//add something here which will uniquely identify the files you want to process, perhaps ${fromDaate}_${toDate}
stringForPattern = '2023-07-01_2025-06-30'
const fileNameRegexPattern = new RegExp(`${stringForPattern}.*\\.json$`);
console.log(fileNameRegexPattern)

processJSONFiles = require('../processJsonFiles');
processJSONFiles(folderPath,fileNameRegexPattern,optionalFolder = undefined)

//Step Four: Compare your CSVs to inspect the number of elements.
// The dimension which returns fewer elements will be used for iterateSegments. The other dimension will be used in the report requests.
// For now, we achieve this by finding the files and counting the number of rows in each CSV file. They will be saved in Adobe Downloads/Legend/CSV

///Step Five: Create Segments for the dimension with fewer elements
const dimToSegments = require('../utils/dimToSegments');
clientName = 'Legend'

//Remember to paste in the actual name that you used in step one
dimension = 'variables/marketingchannel.marketing-channel-attribution'

//select dates for report used to create segments. Only dimension items with visi
fromDate = '2023-07-01'
toDate = '2025-06-30',
dimSegmentId = 's3938_61bb0165a88ab931afa78e4c' // Master Bot Filter EXCLUDE

retrieveLegendRsid = require('../utils/retrieveLegendRsid');
suite = 'coverscom'
rsid = retrieveLegendRsid(suite)
console.log(rsid)

numPairs = 1

dimToSegments(clientName, dimension, fromDate, toDate, dimSegmentId, rsid, numPairs, debugMode = true)

//Step Six: Create a report request config using the other dimension (the one with more elements) and any metrics you need

requestName = 'LegendClickoutsByGeoregionNAOnly' // This is the name of the report request

// With metrics
const metrics = [
  { metricId: 'cm3938_67877f0e25c74e65d1f3f449', metricName: 'raw_clickouts_linear_7d' },
  { metricId: 'cm3938_68655d7318c56ac719c11a44', metricName: 'raw_clickouts_participation_7d' },
  { metricId: 'cm3938_68655dd05c74c471e8de44d0', metricName: 'unique_visit_clickouts_linear_7d' },
  { metricId: 'cm3938_68655e0b18c56ac719c11a47', metricName: 'unique_visit_clickouts_participation_7d' }
];

clientName = 'Legend'
dimension = 'variables/georegion'

//Add segments in the array with comma separation
//Add master bot segment for Legend
//Add Regions = USA and Canada to limit data in this report
masterBotSegment = 's3938_61bb0165a88ab931afa78e4c' // Master Bot Filter EXCLUDE
usaCanadaOnlySegment = 's3938_681e521d16e3be6770921fa8' // USA and Canada Only Segment

segments = [masterBotSegment,usaCanadaOnlySegment] // Master Bot Filter EXCLUDE

const addRequestDetails = require('../utils/addRequestDetails');
addRequestDetails(clientName, requestName, dimension, segments, null, metrics)


//Step Seven: Run a test report to ensure that the request is valid
const downloadAdobeTable = require('../downloadAdobeTable');
requestName = 'LegendClickoutsByGeoregionNAOnly'
reportFromDate = '2025-07-01'
reportToDate = '2025-07-02'
clientName = 'Legend'
additionalSegment = undefined
retrieveLegendRsid = require('../utils/retrieveLegendRsid');
suite = 'coverscom'
rsid = retrieveLegendRsid(suite)
console.log(rsid)
downloadAdobeTable(reportFromDate, reportToDate, requestName, clientName, additionalSegment, rsid)
setTimeout(() => {
    process.exit(0);
// This is a workaround to ensure that the downloadAdobeTable exits after completion. Large requests may take up tp 5 minutes (300000 ms) to complete.
}, 60000);

//Step Eight: Download all your reports using iterateSegmentsRequests.js  
//WARNING: 
const iterateSegmentRequests = require('../utils/iterateSegmentRequests');

segmentsFilePath = './config/segmentLists/Legend/Legend_tribecasinoorg.test_variablesmarketingchannel.marketing-channel-attribution_segments_2025-07-02.json'
jobName = 'MCRunV1'
fromDate = '2023-07-01'
toDate = '2025-06-30'
requestName = 'LegendClickoutsByGeoregionNAOnly'
clientName = 'Legend'
interval = 'month'
  retrieveLegendRsid = require('../utils/retrieveLegendRsid');
  suite = 'coverscom'
rsid = retrieveLegendRsid(suite)
  console.log(rsid)


iterateSegmentRequests(segmentsFilePath, jobName, delay = 0, fromDate, toDate, requestName, clientName, interval, rsid)

//Step Nine: Transform all your downloaded JSON reports


clientName = 'Legend' //update this
jobName = 'MCRunV1' //update this
fileNameRegexPattern = new RegExp(`${jobName}.*\\.json$`);
optionalFolder = jobName //update this to save to a folder other than clientname/csv
const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath');
folderPath = getJsonStorageFolderPath(clientName)

const processJSONFiles = require('../processJsonFiles');
processJSONFiles(folderPath,fileNameRegexPattern,optionalFolder)

//Step Ten: Concatenate your transformed CSV files

jobName = 'MCRunV1' //update this
fileNameRegexPattern = `.*${jobName}.*csv`
console.log(fileNameRegexPattern)

clientName = 'Legend' //update this

const getCsvStorageFolderPath = require('../utils/getCsvStorageFolderPath');
folderPath = getCsvStorageFolderPath(clientName)

// If you specified an optional folder in the previous step, use this code to search that folder
  const path = require('path');
  optionalFolder = jobName //
  folderPathFinal = path.join(folderPath, optionalFolder);

// If you didn't save to an optional folder, uncomment the next line and comment the block above
//folderPathFinal = folderPath
  console.log(folderPathFinal)

outputFilePath = path.join(folderPathFinal,`${jobName}_concatenated.csv`)
console.log(outputFilePath)

const concatenateCSVs = require('../utils/concatenateCSVs');
concatenateCSVs(folderPathFinal,fileNameRegexPattern,outputFilePath,undefined)

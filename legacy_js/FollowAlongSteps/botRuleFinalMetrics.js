//----------------------------------------------------------------------------------------------------
//HOW TO GET CROSS SITE FIGURES - Unfiltered totals for each rule in each site.

const readBotRulesFromCSV = require('../utils/readBotRulesFromCSV.js');
const downloadFinalBotRuleMetrics = require('../downloadFinalBotRuleMetrics.js');

async function main() {
  const fileName = 'Apr25ValidatedList-Aug25Additions.csv';
  const segmentsFilePath = await readBotRulesFromCSV(fileName, 'segmentList');
  console.log('Segments file path:', segmentsFilePath);


  //UPDATE THE VALUES HERE
  jobName = 'FinalBotRuleMetrics-Apr25'
  fromDate = '2025-07-01'
  toDate = '2025-07-11'
  requestName = 'LegendFinalBotMetricsUnfilteredVisitsByYear'
  interval = 'full'

  // Now you can use the segmentsFilePath
  await downloadFinalBotRuleMetrics(
    segmentsFilePath,
    jobName,
    0, //delay
    fromDate,
    toDate,
    requestName,
    'Legend', //clientName
    interval
  );
}

// Run the main function
main().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});

//call downloadFinalBotRuleMetrics

//TRANSFORM AND CONCAT your final bot rule metrics
const finalBotRuleMetricsTransformConcat = require('../finalBotRuleMetricsTransformConcat.js');
const iterateRsidRequests = require('../utils/iterateRsidRequests.js');
finalBotRuleMetricsTransformConcat('Legend', ['FinalBotRuleMetrics-Apr25']);

//----------------------------------------------------------------------------------------------------
//Download totals per RSID for the Development Include segment
const iterateRsidRequests = require('../utils/iterateRsidRequests');

rsidCleanNameList = require('../usefulInfo/Legend/botInvestigationMinThresholdVisits.js');
fromDate = '2025-07-01'
toDate = '2025-07-11'
requestName = 'LegendFinalBotMetricsDevelopmentIncludeByYear'
clientName = 'Legend'
dimSegmentID = undefined
fileNameExtra = 'Apr25TotalExclusionMetrics'
interval = 'full'
const delay = 0; // Delay in milliseconds between requests

iterateRsidRequests(rsidCleanNameList,fromDate, toDate, requestName, clientName, undefined, fileNameExtra,interval,delay)


//Transform all your downloaded JSON reports


clientName = 'Legend' //update this
jobName = 'LegendFinalBotMetricsDevelopmentIncludeByYear_Apr25TotalExclusionMetrics' //update this
fileNameRegexPattern = new RegExp(`${jobName}.*\\.json$`);
optionalFolder = jobName //update this to save to a folder other than clientname/csv
const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath');
folderPath = getJsonStorageFolderPath(clientName)

const processJSONFiles = require('../processJsonFiles');
processJSONFiles(folderPath,fileNameRegexPattern,optionalFolder)

//Step Ten: Concatenate your transformed CSV files

jobName = 'LegendFinalBotMetricsDevelopmentIncludeByYear_Apr25TotalExclusionMetrics' //update this
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

//----------------------------------------------------------------------------------------------------
//Download totals per RSID for the Development CURRENT segment
const iterateRsidRequests = require('../utils/iterateRsidRequests');

rsidCleanNameList = require('../usefulInfo/Legend/botInvestigationMinThresholdVisits.js');
fromDate = '2025-07-01'
toDate = '2025-07-11'
requestName = 'LegendFinalBotMetricsCurrentIncludeByYear'
clientName = 'Legend'
dimSegmentID = undefined
fileNameExtra = 'Apr25TotalExclusionMetrics'
interval = 'full'
const delay = 0; // Delay in milliseconds between requests

iterateRsidRequests(rsidCleanNameList,fromDate, toDate, requestName, clientName, undefined, fileNameExtra,interval,delay)


//Transform all your downloaded JSON reports


clientName = 'Legend' //update this
jobName = 'LegendFinalBotMetricsCurrentIncludeByYear_Apr25TotalExclusionMetrics' //update this
fileNameRegexPattern = new RegExp(`${jobName}.*\\.json$`);
optionalFolder = jobName //update this to save to a folder other than clientname/csv
const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath');
folderPath = getJsonStorageFolderPath(clientName)

const processJSONFiles = require('../processJsonFiles');
processJSONFiles(folderPath,fileNameRegexPattern,optionalFolder)

//Step Ten: Concatenate your transformed CSV files

jobName = 'LegendFinalBotMetricsCurrentIncludeByYear_Apr25TotalExclusionMetrics' //update this
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

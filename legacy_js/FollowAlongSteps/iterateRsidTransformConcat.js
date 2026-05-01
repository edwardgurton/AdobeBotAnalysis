// Iterate through the rsids for your request
const iterateRsidRequests = require('../utils/iterateRsidRequests.js');

const rsidCleanNameList = require('../usefulInfo/Legend/botInvestigationMinThresholdVisits.js');
fromDate = '2025-07-01'
toDate = '2025-07-10'
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
const getJsonStorageFolderPath = require('../utils/getJsonStorageFolderPath.js');
folderPath = getJsonStorageFolderPath(clientName)

const processJSONFiles = require('../processJsonFiles.js');
processJSONFiles(folderPath,fileNameRegexPattern,optionalFolder)

//Step Ten: Concatenate your transformed CSV files

jobName = 'LegendFinalBotMetricsDevelopmentIncludeByYear_Apr25TotalExclusionMetrics' //update this
fileNameRegexPattern = `.*${jobName}.*csv`
console.log(fileNameRegexPattern)

clientName = 'Legend' //update this

const getCsvStorageFolderPath = require('../utils/getCsvStorageFolderPath.js');
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

const concatenateCSVs = require('../utils/concatenateCSVs.js');
concatenateCSVs(folderPathFinal,fileNameRegexPattern,outputFilePath,undefined)


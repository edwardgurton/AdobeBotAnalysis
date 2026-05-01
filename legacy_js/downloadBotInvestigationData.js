const iterateDateRequests = require('./utils/iterateDateRequests.js');
const fs = require('fs');
const yaml = require('js-yaml');
const legendRsidList = './usefulInfo/Legend/legendReportSuites.txt'
const retrieveValue = require('./utils/retrieveValue.js')
const subtractDays = require('./utils/subtractDays.js')
const downloadAdobeTable = require('./downloadAdobeTable.js')

async function downloadBotInvestigationData(delay=0, fromDate, toDate, clientName='Legend', dimSegmentId=undefined, rsid="default", investigationName) {
    try {
        console.log(`📊 Starting ${investigationName} - processing 11 report types concurrently...`);
        
        // Make all requests at same time; totals then daily
        const reportPromises = [
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByMarketingChannel', clientName, dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByMobileManufacturer', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByDomain', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByMonitorResolution', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByHourOfDay', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByOperatingSystem', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByPageURL', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByRegion', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByUserAgent', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationMetricsByBrowserType', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),

            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByDay', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByMarketingChannel', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByMobileManufacturer', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByDomain', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByMonitorResolution', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByHourOfDay', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByOperatingSystem', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByPageURL', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByRegion', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByUserAgent', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationMetricsByBrowserType', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`)
        ];

        // Wait for all report types to complete
        await Promise.all(reportPromises);
        
        console.log(`✅ ${investigationName} - All 11 report types completed successfully.`);
    } catch (error) {
        console.error(`❌ ${investigationName} - An error occurred:`, error);
        throw error; // Re-throw so calling code can handle it
    }
}

module.exports = downloadBotInvestigationData;

//With bot investigation, toDate needs to be following day

// const suite = 'coverscom'
// const rsid = retrieveValue(legendRsidList,suite,'right')
// const dimSegmentId = 's3938_6780ffad8e0db45770364b00'
// console.log(rsid)
// const toDate = '2025-03-25';
// const investigationPrefix = `${suite}-Phillipines-${toDate}`;
// const fromDate = subtractDays(toDate,90)

//downloadBotInvestigationData(0,fromDate,toDate,'Legend',dimSegmentId,rsid,investigationPrefix)

// //with iterate date requests, end date is the last full day of data. So unlike downloadAdobeTable, it doesn't need to be the following day.
//async function iterateDateRequests(delay = 0, fromDate, toDate, requestName, clientName, interval = 'day', dimSegmentID = undefined, rsid="default", fileNameExtra = undefined)
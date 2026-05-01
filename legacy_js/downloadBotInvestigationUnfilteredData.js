const iterateDateRequests = require('./utils/iterateDateRequests.js');
const fs = require('fs');
const yaml = require('js-yaml');
const legendRsidList = './usefulInfo/Legend/legendReportSuites.txt'
const retrieveValue = require('./utils/retrieveValue.js')
const subtractDays = require('./utils/subtractDays.js')
const downloadAdobeTable = require('./downloadAdobeTable.js')

async function downloadbotInvestigationUnfilteredData(delay=0, fromDate, toDate, clientName='Legend', dimSegmentId=undefined, rsid="default", investigationName) {
    try {
        console.log(`📊 Starting ${investigationName} - processing 11 report types concurrently...`);
        
        // Make all requests at same time; totals then daily
        const reportPromises = [
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByMarketingChannel', clientName, dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByMobileManufacturer', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByDomain', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByMonitorResolution', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByHourOfDay', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByOperatingSystem', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByPageURL', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByRegion', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByUserAgent', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),
            downloadAdobeTable(fromDate, toDate,'botInvestigationUnfilteredMetricsByBrowserType', clientName,dimSegmentId,rsid,`${investigationName}-Totals`),

            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByDay', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByMarketingChannel', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByMobileManufacturer', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByDomain', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByMonitorResolution', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByHourOfDay', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByOperatingSystem', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByPageURL', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByRegion', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByUserAgent', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`),
            iterateDateRequests(delay, fromDate, toDate,'botInvestigationUnfilteredMetricsByBrowserType', clientName,'day',dimSegmentId,rsid,`${investigationName}-Daily`)
        ];

        // Wait for all report types to complete
        await Promise.all(reportPromises);
        
        console.log(`✅ ${investigationName} - All 11 report types completed successfully.`);
    } catch (error) {
        console.error(`❌ ${investigationName} - An error occurred:`, error);
        throw error; // Re-throw so calling code can handle it
    }
}

module.exports = downloadbotInvestigationUnfilteredData;

//With bot investigation, toDate needs to be following day

// const suite = 'coverscom'
// const rsid = retrieveValue(legendRsidList,suite,'right')
// const dimSegmentId = 's3938_6780ffad8e0db45770364b00'
// console.log(rsid)
// const toDate = '2025-03-25';
// const investigationPrefix = `${suite}-Phillipines-${toDate}`;
// const fromDate = subtractDays(toDate,90)

//downloadbotInvestigationUnfilteredData(0,fromDate,toDate,'Legend',dimSegmentId,rsid,investigationPrefix)

// //with iterate date requests, end date is the last full day of data. So unlike downloadAdobeTable, it doesn't need to be the following day.
//async function iterateDateRequests(delay = 0, fromDate, toDate, requestName, clientName, interval = 'day', dimSegmentID = undefined, rsid="default", fileNameExtra = undefined)
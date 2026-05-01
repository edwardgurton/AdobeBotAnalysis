const yaml = require('js-yaml');
const fs = require('fs');
const _ = require('lodash'); // Lodash library for deep cloning

/**
 * Compiles a request configuration for Adobe Analytics based on provided parameters.
 * 
 * @param {string} fromDate - The start date for the date range filter (format: YYYY-MM-DD).
 * @param {string} toDate - The end date for the date range filter (format: YYYY-MM-DD).
 * @param {string} requestName - The name of the request to be processed from the client configuration.
 * @param {string} clientName - The name of the client to load specific configuration settings.
 * @param {string} dimSegmentID - Optional. An additional segment ID to filter the data by a specific dimension.
 * @param {string} [rsid='default'] - Optional. The Report Suite ID to use. Defaults to 'default'.
 * 
 * @returns {object} The compiled request data with applied filters and configurations.
 */
function compileRequest(fromDate, toDate, requestName, clientName, dimSegmentID, rsid = 'default') {
    const dateRangeGlobalFilter = {
        type: "dateRange",
        dateRange: `${fromDate}T00:00:00.000/${toDate}T00:00:00.000`,
    };
    
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${clientName}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        return;
    }

    const reportConfig = config.reportConfig;
    const configRsid = config.adobe.rsid; // Get the RSID from the config file

    // Use the provided rsid argument unless it's 'default', in which case use configRsid
    const finalRsid = rsid === 'default' ? configRsid : rsid;

    // Load and deep clone the request template to ensure each iteration uses a fresh copy
    const requestBody = _.cloneDeep(require(`../config/requests/templateRequest`));

    let updatedRequestData = {
        ...requestBody,
        rsid: finalRsid, // Use the final RSID
        globalFilters: Array.isArray(requestBody.globalFilters) ? [...requestBody.globalFilters, dateRangeGlobalFilter] : [dateRangeGlobalFilter],
    };

    // Handle multiple segments
    let segmentIds = reportConfig[requestName]?.segmentId;
    if (segmentIds) {
        const segments = segmentIds.split(',').map(id => id.trim());
        //console.log("Processing global filter segments:", segments);
        
        segments.forEach(segmentId => {
            if (segmentId) {
                const segmentFilter = { type: "segment", segmentId: segmentId };
                updatedRequestData.globalFilters.push(segmentFilter);
                console.log("Added segment filter:", segmentId);
            }
        });
    } else {
        console.log("No global filter segments specified");
    }

    if (dimSegmentID) {
        const segmentFilter = { type: "segment", segmentId: dimSegmentID };
        updatedRequestData.globalFilters.push(segmentFilter);
        //console.log("Added dimension segment filter:", dimSegmentID);
    }

    // Conditionally add the metric objects
    if (reportConfig[requestName]?.addMetrics) {
        // Ensure metricContainer.metrics array exists
        if (!updatedRequestData.metricContainer) {
            updatedRequestData.metricContainer = { metrics: [] };
        } else if (!updatedRequestData.metricContainer.metrics) {
            updatedRequestData.metricContainer.metrics = [];
        }
        //console.log("adding metrics to request body");
        
        // Get the metric IDs and add them to the metrics array
        const metricIds = reportConfig[requestName]?.metricIds;

        if (metricIds) {
            const ids = metricIds.split(',').map(id => id.trim());
            ids.forEach((id, index) => {
                updatedRequestData.metricContainer.metrics.push({
                    columnId: (index + 2).toString(),
                    id: id
                });
                //console.log("added metric:", id, "to the body");
            });
        }
    }

    // Conditionally add the dimension object
    if (reportConfig[requestName]?.addDimension) {
        let dimensionId = reportConfig[requestName]?.dimensionId;

        if (dimensionId) {
            //console.log("added dimension", dimensionId, "to request");
            // Add the dimension to updatedRequestData
            updatedRequestData.dimension = dimensionId;
        }
    }

    // Add rowLimit to the settings object
    const rowLimit = reportConfig[requestName]?.rowLimit || 100;
    if (!updatedRequestData.settings) {
        updatedRequestData.settings = {};
    }
    updatedRequestData.settings.limit = rowLimit;
    //console.log(`Set row limit to ${rowLimit}`);

    return updatedRequestData;
}

module.exports = compileRequest;
// Enhanced getAdobeTable.js - Let 429 errors bubble up
const axios = require('axios');
const yaml = require('js-yaml');
const fs = require('fs');
const getAdobeAccessToken = require('./getAdobeAccessToken');
const compileRequest = require('./compileRequest');

async function getAdobeTable(fromDate, toDate, requestName, clientName, dimSegmentID = undefined, rsid = "default") {
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${clientName}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        return null;
    }

    const { adobeOrgID, globalCompanyID, clientID } = config.adobe || {};

    if (!adobeOrgID || !globalCompanyID || !clientID) {
        console.error('Missing required Adobe configuration');
        return null;
    }

    try {
        const accessToken = await getAdobeAccessToken(clientName);

        if (accessToken) {
            const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/reports`;
            const headers = {
                'Accept': 'application/json',
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json;charset=utf-8',
                'x-api-key': clientID,
                'x-proxy-global-company-id': globalCompanyID,
                'x-gw-ims-org-id': adobeOrgID,
            };

            const requestBody = compileRequest(fromDate, toDate, requestName, clientName, dimSegmentID, rsid);
            //console.log("Request Body: ", requestBody);

            //console.log("Posting Request to Axios")
            const response = await axios.post(apiUrl, requestBody, { headers });
            //console.log("response in full", response)
            return response.data;
        } else {
            throw new Error('Failed to get access token');
        }
    } catch (error) {
        // Let 429 errors bubble up for special handling
        if (error.response && error.response.status === 429) {
            throw error; // Re-throw 429 errors
        }
        
        console.error('API Response Error:', error);
        return null;
    }
}

module.exports = getAdobeTable;

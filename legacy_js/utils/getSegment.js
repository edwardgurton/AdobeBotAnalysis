const axios = require('axios');
const yaml = require('js-yaml');
const fs = require('fs');
const getAdobeAccessToken = require('./getAdobeAccessToken');

async function getExpandedSegmentDetails(segmentId, clientName) {
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
        // Get the Adobe access token
        const accessToken = await getAdobeAccessToken(clientName);

        // Adobe Analytics API endpoint for retrieving segment details
        const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/segments/${segmentId}?expansion=definition`;

        // Make the API request to get expanded segment details
        const response = await axios.get(apiUrl, {
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json',
                'x-api-key': clientID,
                'x-proxy-global-company-id': globalCompanyID,
                'x-gw-ims-org-id': adobeOrgID,
            }
        });

        return response.data;

    } catch (error) {
        console.error('Error retrieving expanded segment details:', error.response ? error.response.data : error.message);
        throw error;
    }
}

module.exports = getExpandedSegmentDetails

// // Usage
// getExpandedSegmentDetails('s3938_5f350ab3e9eaeb0c29b70489', 'Legend')
//     .then(details => console.log(JSON.stringify(details, null, 2)))
//     .catch(error => console.error('Error:', error.message));
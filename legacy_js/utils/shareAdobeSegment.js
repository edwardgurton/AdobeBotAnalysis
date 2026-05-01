// shareAdobeSegment.js
const axios = require('axios');
const yaml = require('js-yaml');
const fs = require('fs');
const getAdobeAccessToken = require('./getAdobeAccessToken');

async function shareAdobeSegment(segmentId, userId, clientName) {
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

        if (!accessToken) {
            throw new Error('Failed to get access token');
        }

        const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/componentmetadata/shares`;
        const headers = {
            'Accept': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
            'x-api-key': clientID,
            'x-proxy-global-company-id': globalCompanyID,
            'x-gw-ims-org-id': adobeOrgID,
        };

        const requestBody = {
            componentType: "segment",
            componentId: segmentId,
            shareToId: userId,
            shareToType: "user"
        };

        const response = await axios.post(apiUrl, requestBody, { headers });
        console.log(`✓ Successfully shared segment ${segmentId} with user ${userId}`);
        return response.data;

    } catch (error) {
        if (error.response && error.response.status === 429) {
            throw error;
        }
        
        console.error(`✗ Failed to share segment ${segmentId} with user ${userId}:`, error.message);
        return null;
    }
}

module.exports = shareAdobeSegment;
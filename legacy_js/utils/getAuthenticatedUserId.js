const yaml = require('js-yaml');
const fs = require('fs');
const axios = require('axios');
const getAdobeAccessToken = require('./getAdobeAccessToken');

async function getAuthenticatedUserId(clientName) {
    // Load client configuration
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
        // Get access token
        const accessToken = await getAdobeAccessToken(clientName);
        if (!accessToken) {
            throw new Error('Failed to get access token');
        }

        // Set up request headers
        const apiUrl = `https://analytics.adobe.io/discovery/me`;
        const headers = {
            'Accept': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
            'x-api-key': clientID,
        };

        // Send request to get user information
        const response = await axios.get(apiUrl, { headers });

        if (response.status === 200) {
            const imsUserId = response.data.imsUserId;
            console.log(`Authenticated user ID: ${imsUserId}`);
            return imsUserId;
        } else {
            throw new Error(`Failed to get user information. Status: ${response.status}`);
        }
    } catch (error) {
        console.error('Error getting authenticated user ID:', error.message);
        return null;
    }
}

module.exports = getAuthenticatedUserId;

const clientName = 'Capita'

getAuthenticatedUserId(clientName)
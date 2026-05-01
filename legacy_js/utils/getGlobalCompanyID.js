const fs = require('fs');
const yaml = require('js-yaml');
const axios = require('axios');
const getAdobeAccessToken = require('./getAdobeAccessToken');

async function getGlobalCompanyID(clientName) {

    // Load client configuration from YAML file
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${clientName}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        return;
    }

    const { clientID, clientSecret, apiKey, globalCompanyID } = config.adobe;
    console.log("clientID:", clientID, )

    // URL with placeholder replaced
    const url = `https://analytics.adobe.io/discovery/me`;

    try {
        // Get Adobe access token
        const accessToken = await getAdobeAccessToken(clientID, clientSecret);

        if (!accessToken) {
            console.error('Failed to obtain access token');
            return;
        }

        // Fetch company info from Adobe Analytics API using axios
        const response = await axios.get(url, {
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'x-api-key': clientID,
            }
        });

        //console.log('Company Info:', response.data.imsOrgs[0].companies[0].globalCompanyId);

        // Assuming the response contains the globalCompanyID
        console.log('Global Company ID:', response.data.imsOrgs[0].companies[0].globalCompanyId);
        return response.data.imsOrgs[0].companies[0].globalCompanyId;

    } catch (error) {
        if (error.response) {
            console.error(`Error: ${error.response.status} ${error.response.statusText}`);
        } else {
            console.error('Error fetching globalCompanyID:', error.message);
        }
    }
}

module.exports = getGlobalCompanyID;

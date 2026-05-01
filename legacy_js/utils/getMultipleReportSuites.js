const fs = require('fs');
const yaml = require('js-yaml');
const axios = require('axios');
const getAdobeAccessToken = require('./getAdobeAccessToken');
const saveJSONData = require('./saveJSONData')

async function getMultipleReportSuites(clientName, fileName) {


console.log("file path for trying/", `./config/client_configs/client${clientName}.yaml`)
    // Load client configuration from YAML file
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${clientName}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        return;
    }

    const { clientID, clientSecret, globalCompanyID } = config.adobe;
    console.log("clientID:", clientID,"/globalCompanyID", globalCompanyID )

    // URL with placeholder replaced
    const url = `https://analytics.adobe.io/api/${globalCompanyID}/reportsuites/collections/suites?limit=1000`;

    try {
        // Get Adobe access token
        const accessToken = await getAdobeAccessToken(clientName);

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
        console.log('Response:', response.data);
       const data = response.data
       saveJSONData(fileName, data);

    } catch (error) {
        if (error.response) {
            console.error(`Error: ${error.response.status} ${error.response.statusText}`);
        } else {
            console.error('Error fetching report suites:', error.message);
        }
    }
}

//getMultipleReportSuites("Legend","legend report suites v3")

module.exports = getMultipleReportSuites

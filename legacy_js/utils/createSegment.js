//YOU HAVE TO INCLUDE VERSION!

const yaml = require('js-yaml');
const fs = require('fs');
const axios = require('axios');
const getAdobeAccessToken = require('./getAdobeAccessToken');

async function createAdobeSegment(clientName, dimensionName, itemId, value) {
    // Load client configuration
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${clientName}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        return null;
    }

    const { adobeOrgID, globalCompanyID, clientID, rsid } = config.adobe || {};
    if (!adobeOrgID || !globalCompanyID || !clientID || !rsid) {
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
        const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/segments`;
        const headers = {
            'Accept': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
            'x-api-key': clientID,
            'x-proxy-global-company-id': globalCompanyID,
            'x-gw-ims-org-id': adobeOrgID,
        };

        // Construct segment definition
        const segmentName = `${dimensionName} = ${value}`;
        const idNum = parseInt(itemId)
        const segmentDefinition = {
            "name": `${segmentName}`,
            "description": "Created via API",
            "definition": {
              "container": {
                "func": "container",
                "context": "hits",
                "pred": {
                  "val": {
                    "func": "attr",
                    "name": `${dimensionName}`
                  },
                  "func": "eq",
                  "num": idNum,
                  "description": "Countries"
                }
              },
              "func": "segment",
              "version": [
                1,
                0,
                0
              ]
            },
            "isPostShardId": true,
            "rsid": `${rsid}`,
            // "owner": {
            //   "id": 200249009
            // }
          }
        console.log(segmentDefinition.definition.container.pred)

        // Send request to create segment
        const response = await axios.post(apiUrl, segmentDefinition, { headers });

        if (response.status === 200 || response.status === 201) {
            const { id, name } = response.data;
            console.log(`Segment created successfully. ID: ${id}, Name: ${name}`);
            return { id, name };
        } else {
            throw new Error(`Failed to create segment. Status: ${response.status}`);
        }
    } catch (error) {
        console.error('Error creating Adobe segment:', error);
        return null;
    }
}

module.exports = { createAdobeSegment };

// const clientName = 'Capita'
// const dimensionName = 'variables/marketingchannel'
// const itemId = 10
// const value = 'Job Board'

// createAdobeSegment(clientName,dimensionName,itemId,value)


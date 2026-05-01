// getAdobeUsers.js
const axios = require('axios');
const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');
const getAdobeAccessToken = require('./getAdobeAccessToken');

async function getAdobeUsers(clientName) {
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

        const headers = {
            'Accept': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json;charset=utf-8',
            'x-api-key': clientID,
            'x-proxy-global-company-id': globalCompanyID,
            'x-gw-ims-org-id': adobeOrgID,
        };

        let allUsers = [];
        let page = 0;
        let hasMorePages = true;

        while (hasMorePages) {
            const apiUrl = `https://analytics.adobe.io/api/${globalCompanyID}/users?limit=100&page=${page}`;
            const response = await axios.get(apiUrl, { headers });
            
            if (response.data && response.data.content) {
                allUsers = allUsers.concat(response.data.content);
                hasMorePages = !response.data.lastPage;
                page++;
            } else {
                hasMorePages = false;
            }
        }

        const today = new Date().toISOString().split('T')[0];
        const dirPath = path.join('usefulInfo', clientName, 'userLists');
        const filePath = path.join(dirPath, `userList-${today}.json`);

        fs.mkdirSync(dirPath, { recursive: true });
        fs.writeFileSync(filePath, JSON.stringify(allUsers, null, 2));

        return filePath;

    } catch (error) {
        if (error.response && error.response.status === 429) {
            throw error;
        }
        
        console.error('API Response Error:', error);
        return null;
    }
}

module.exports = getAdobeUsers;
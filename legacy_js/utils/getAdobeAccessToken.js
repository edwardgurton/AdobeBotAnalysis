const axios = require('axios');
const yaml = require('js-yaml');
const fs = require('fs');

async function getAdobeAccessToken(clientName) {
    let config;
    try {
        config = yaml.load(fs.readFileSync(`./config/client_configs/client${clientName}.yaml`, 'utf8'));
    } catch (e) {
        console.error('Error loading client configuration:', e);
        return null;
    }

    const { clientID, clientSecret } = config.adobe || {};

    if (!clientID || !clientSecret) {
        console.error('Client ID or Client Secret not found in configuration');
        return null;
    }

    const tokenEndpoint = 'https://ims-na1.adobelogin.com/ims/token/v3';
    const postData = `grant_type=client_credentials&client_id=${clientID}&client_secret=${clientSecret}&scope=openid,AdobeID,additional_info.projectedProductContext`;
  
    try {
        const response = await axios.post(tokenEndpoint, postData, {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
        });
  
        if (response.status === 200) {
            const accessToken = response.data.access_token;
            return accessToken;
        } else {
            console.error('Failed to obtain access token.');
            return null;
        }
    } catch (error) {
        console.error('Access Token Error:', error.message);
        return null;
    }
}

module.exports = getAdobeAccessToken;
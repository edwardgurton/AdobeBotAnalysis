const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');

function getJsonStorageFolderPath(clientName) {
    let readWriteSettings;
    try {
        readWriteSettings = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
    } catch (error) {
        console.error('Error loading read/write settings:', error);
        throw error; // Re-throw to let the caller handle it
    }

    const storageFolder = readWriteSettings.storage.folder;
    const folderPath = path.join(storageFolder, clientName, 'JSON');
    
    return folderPath;
}

module.exports = getJsonStorageFolderPath;
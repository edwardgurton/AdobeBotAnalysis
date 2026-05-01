const axios = require('axios');
const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');

//fromDate is date in format YYYY-MM-DD
//toDate is date in format YYYY-MM-DD
//requestName must match headers in client_configs file. It will also be used to create filename
//clientName must match name of client_configs file. It will also be used to create filename
//dimSegmentID can be optionally inputted to apply a segmentID to the request. This segmentID will be saved in the file name. It's intended for use when creating segments for each value in a dimension.



async function saveJSONData(fileName, data) {

  let readWriteConfig;
  try {
    readWriteConfig = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
    console.log('Read/Write Configuration:', readWriteConfig); // Log the configuration to verify
  } catch (e) {
    console.error('Error loading read/write configuration:', e);
    return;
  }

  const { folder: baseFolder } = readWriteConfig.storage || {};
  if (!baseFolder) {
    console.error('Base folder is undefined in read/write configuration.');
    return;
  }
  try {

      console.log("baseFolder: ", baseFolder)
      const folderPath = path.join(baseFolder, 'savedOutputs');
      console.log('Folder path:', folderPath);
      if (!fs.existsSync(folderPath)) {
        fs.mkdirSync(folderPath, { recursive: true });
      }

      let filename = path.join(folderPath, `${fileName}.json`);

      console.log('Filename:', filename);
      fs.writeFileSync(filename, JSON.stringify(data, null, 2));
      console.log('Saved to local drive:', filename);
    }
   catch (error) {
    console.error('Saving Error', error);
  }
}


module.exports = saveJSONData;
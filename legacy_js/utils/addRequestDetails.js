const fs = require('fs');
const yaml = require('js-yaml');
const path = require('path');

function addRequestDetails(clientName, requestName, dimension, segments = [], rowLimit = null, metrics = null) {
  // Construct the file path
  const filePath = path.join('config', 'client_configs', `client${clientName}.yaml`);
  
  // Clean the request name by removing spaces and special characters
  const cleanedRequestName = requestName.replace(/[^a-zA-Z0-9]/g, '');

  try {
    // Read the existing YAML file
    const fileContents = fs.readFileSync(filePath, 'utf8');
    const data = yaml.load(fileContents);

    // Process segments
    let segmentId = '';
    if (segments && Array.isArray(segments) && segments.length > 0) {
      segmentId = segments.join(', ');
    }

    // Process metrics
    let addMetrics = false;
    let metricIds = '';
    let metricNames = [];

    if (metrics && Array.isArray(metrics) && metrics.length > 0) {
      addMetrics = true;
      const metricIdArray = [];
      
      for (const metric of metrics) {
        if (metric.metricId && metric.metricName) {
          metricIdArray.push(metric.metricId);
          metricNames.push(metric.metricName);
        }
      }
      
      metricIds = metricIdArray.join(', ');
    }

    // Create the new report configuration
    const newConfig = {
      [cleanedRequestName]: {
        segmentId: segmentId,
        addMetrics: addMetrics,
        metricIds: metricIds,
        addDimension: true,
        dimensionId: dimension
      }
    };

    // Add the row limit if provided
    if (rowLimit !== null) {
      newConfig[cleanedRequestName].rowLimit = rowLimit;
    }

    // Add the new configuration to the existing data
    if (!data.reportConfig) {
      data.reportConfig = {};
    }
    Object.assign(data.reportConfig, newConfig);

    // Convert the updated data back to YAML
    const updatedYaml = yaml.dump(data, { quotingType: '"' });

    // Write the updated YAML back to the file
    fs.writeFileSync(filePath, updatedYaml, 'utf8');

    // Generate headers file
    generateHeadersFile(clientName, dimension, cleanedRequestName, metricNames);

    console.log(`Successfully added ${cleanedRequestName} to ${filePath}`);
    console.log(`Successfully generated headers file for ${cleanedRequestName}`);
  } catch (error) {
    console.error(`Error updating YAML file: ${error.message}`);
  }
}

function generateHeadersFile(clientName, dimension, requestName, metricNames = []) {
  try {
    // Create headers directory if it doesn't exist
    const headersDir = path.join('config', 'headers', requestName);
    if (!fs.existsSync(headersDir)) {
      fs.mkdirSync(headersDir, { recursive: true });
    }

    // Build headers array
    // Start with id, dimension, then always include unique_visitors and visits
    let headersArray = ['id', dimension.replace(/[/. ]/g, ''), 'unique_visitors', 'visits'];
    
    // Add additional metric names if provided (these are the ones from the metrics parameter)
    if (metricNames && metricNames.length > 0) {
      headersArray = headersArray.concat(metricNames);
    }
    
    // Add the final three headers
    headersArray.push('fileName', 'fromDate', 'toDate');

    // Create headers string
    const headersString = headersArray.join(',');

    // Generate the headers file content
    const headersFileContent = `//add your headers here as a comma delimited string. 
//Headers order: id, dimension, unique_visitors, visits, [additional metrics], fileName, fromDate, toDate
//Note: unique_visitors and visits are always included in reports by default
// let headers = 'id,region,unique_visitors,visits,custom_metric,fileName,fromDate,toDate'
let headers = '${headersString}'

//new line is added for csv concatenation
if (!headers.endsWith('\\n')) {
    headers += '\\n';
  }

module.exports = headers;
`;

    // Write the headers file
    const headersFilePath = path.join(headersDir, `${clientName}.js`);
    fs.writeFileSync(headersFilePath, headersFileContent, 'utf8');

  } catch (error) {
    console.error(`Error generating headers file: ${error.message}`);
  }
}

module.exports = addRequestDetails;
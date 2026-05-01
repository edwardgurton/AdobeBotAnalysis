const fs = require('fs');
const yaml = require('js-yaml');
const path = require('path');

function deleteRequestDetails(clientName, dimension) {
  // Construct the file path
  const filePath = path.join('config', 'client_configs', `client${clientName}.yaml`);

  try {
    // Read the existing YAML file
    const fileContents = fs.readFileSync(filePath, 'utf8');
    const data = yaml.load(fileContents);

    // Check if the reportConfig exists and the SegmentsBuilder configuration is present
    if (data.reportConfig && data.reportConfig[`SegmentsBuilder${dimension.replace(/\//g, '')}`]) {
      // Delete the SegmentsBuilder configuration
      delete data.reportConfig[`SegmentsBuilder${dimension.replace(/\//g, '')}`];

      // Convert the updated data back to YAML
      const updatedYaml = yaml.dump(data, { quotingType: '"' });

      // Write the updated YAML back to the file
      fs.writeFileSync(filePath, updatedYaml, 'utf8');

      console.log(`Successfully deleted SegmentsBuilder${dimension.replace(/\//g, '')} from ${filePath}`);
    } else {
      console.log(`SegmentsBuilder${dimension.replace(/\//g, '')} not found in ${filePath}`);
    }
  } catch (error) {
    console.error(`Error updating YAML file: ${error.message}`);
  }
}

module.exports = deleteRequestDetails;
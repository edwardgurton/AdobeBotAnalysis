function extractValueId(jsonData) {
    return new Promise((resolve, reject) => {
      try {
        const result = [];
  
        if (jsonData && jsonData.rows) {
          for (const row of jsonData.rows) {
            if (row.value && row.itemId) {
              result.push({
                value: row.value,
                itemId: row.itemId
              });
            }
          }
        }
  
        resolve(result);
      } catch (error) {
        reject(error);
      }
    });
  }

  module.exports = extractValueId
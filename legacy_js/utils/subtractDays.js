function subtractDays(dateString, daysToSubtract) {
  const date = new Date(dateString);
  date.setDate(date.getDate() - daysToSubtract);

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');

  return `${year}-${month}-${day}`;
}

module.exports = subtractDays

// fromDate = '2024-07-17'
// console.log(subtractDays(fromDate,30))
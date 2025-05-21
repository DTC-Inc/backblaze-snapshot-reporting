// JavaScript for Backblaze Snapshot Reporting

document.addEventListener('DOMContentLoaded', function() {
    // Enable tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });

    // Format numbers for better readability
    document.querySelectorAll('.format-number').forEach(function(element) {
        const value = parseFloat(element.textContent);
        element.textContent = new Intl.NumberFormat().format(value);
    });

    // Format costs with dollar sign
    document.querySelectorAll('.format-cost').forEach(function(element) {
        const value = parseFloat(element.textContent);
        element.textContent = '$' + value.toFixed(2);
    });

    // Format dates
    document.querySelectorAll('.format-date').forEach(function(element) {
        const dateStr = element.textContent;
        const date = new Date(dateStr);
        element.textContent = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    });

    // Add event listeners for snapshot filtering
    const snapshotFilter = document.getElementById('snapshotFilter');
    if (snapshotFilter) {
        snapshotFilter.addEventListener('change', function() {
            const days = parseInt(this.value);
            window.location.href = '/snapshots?days=' + days;
        });
    }

    // Add event listeners for cost threshold changes
    const thresholdFilter = document.getElementById('thresholdFilter');
    if (thresholdFilter) {
        thresholdFilter.addEventListener('change', function() {
            const threshold = parseFloat(this.value);
            window.location.href = '/?threshold=' + threshold;
        });
    }

    // Initialize cost trends chart if the element exists
    const costTrendsChartEl = document.getElementById('costTrendsChart');
    if (costTrendsChartEl) {
        initCostTrendsChart();
    }
    
    // Initialize storage breakdown chart if the element exists
    const storageChartEl = document.getElementById('storageBreakdownChart');
    if (storageChartEl) {
        initStorageBreakdownChart();
    }
    
    // Set up download report button
    const downloadReportBtn = document.getElementById('downloadReportBtn');
    if (downloadReportBtn) {
        downloadReportBtn.addEventListener('click', generateReport);
    }

    // Snapshot Progress Handling
    const takeSnapshotBtn = document.getElementById('takeSnapshotBtn');
    const snapshotProgressContainer = document.getElementById('snapshotProgressContainer');
    const snapshotProgressBar = document.getElementById('snapshotProgressBar');
    const snapshotStatusText = document.getElementById('snapshotStatusText');
    const snapshotMessageText = document.getElementById('snapshotMessageText');
    let progressInterval;

    if (takeSnapshotBtn) {
        // Check initial progress on page load
        updateSnapshotProgress(); 

        takeSnapshotBtn.addEventListener('click', function(event) {
            // Form submission will be handled by the browser, triggering the backend.
            // Start polling for progress immediately.
            if (snapshotProgressContainer) snapshotProgressContainer.style.display = 'block';
            if (snapshotStatusText) snapshotStatusText.textContent = 'Snapshot initiated...';
            if (snapshotProgressBar) {
                snapshotProgressBar.style.width = '0%';
                snapshotProgressBar.textContent = '0%';
                snapshotProgressBar.setAttribute('aria-valuenow', '0');
                snapshotProgressBar.classList.remove('bg-success', 'bg-danger', 'bg-primary');
                snapshotProgressBar.classList.add('progress-bar-animated', 'progress-bar-striped', 'bg-primary');
            }
            if (snapshotMessageText) snapshotMessageText.textContent = 'Waiting for snapshot to start...';
            
            const viewDetailsBtn = document.getElementById('viewProgressDetailsBtn');
            if(viewDetailsBtn) viewDetailsBtn.style.display = 'inline-block'; // Show immediately on new snapshot

            if (progressInterval) {
                clearInterval(progressInterval);
            }
            progressInterval = setInterval(updateSnapshotProgress, 2000); 
        });
    }

    function updateSnapshotProgress() {
        fetch('/snapshot/progress') // This endpoint returns snapshot_progress_global
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (!snapshotProgressContainer || !snapshotProgressBar || !snapshotStatusText || !snapshotMessageText) {
                    if (progressInterval) clearInterval(progressInterval);
                    return;
                }

                const viewDetailsBtn = document.getElementById('viewProgressDetailsBtn');
                let currentStatus = 'idle';

                if (data.error_message) {
                    currentStatus = 'error';
                } else if (data.active) {
                    currentStatus = 'running';
                } else if (!data.active && data.overall_percentage === 100) {
                    currentStatus = 'completed';
                } else if (!data.active && data.overall_percentage === 0 && !data.start_time) {
                    currentStatus = 'idle'; // Or 'pending'
                }


                if (currentStatus !== 'idle' || data.overall_percentage > 0) {
                    snapshotProgressContainer.style.display = 'block';
                } else {
                    snapshotProgressContainer.style.display = 'none';
                }
                
                if (viewDetailsBtn) {
                    viewDetailsBtn.style.display = data.active ? 'inline-block' : 'none';
                }

                snapshotProgressBar.style.width = data.overall_percentage + '%';
                snapshotProgressBar.textContent = data.overall_percentage + '%';
                snapshotProgressBar.setAttribute('aria-valuenow', data.overall_percentage);
                snapshotMessageText.textContent = data.status_message || 'Fetching status...';


                snapshotProgressBar.classList.remove('bg-success', 'bg-danger', 'bg-primary', 'progress-bar-animated', 'progress-bar-striped');

                if (currentStatus === 'running') {
                    snapshotStatusText.textContent = 'Snapshot Running...';
                    snapshotProgressBar.classList.add('bg-primary', 'progress-bar-animated', 'progress-bar-striped');
                    if (!progressInterval) { 
                         progressInterval = setInterval(updateSnapshotProgress, 2000);
                    }
                } else if (currentStatus === 'completed') {
                    snapshotStatusText.textContent = 'Snapshot Completed';
                    snapshotProgressBar.classList.add('bg-success');
                    if (progressInterval) clearInterval(progressInterval);
                     if (viewDetailsBtn) viewDetailsBtn.style.display = 'inline-block'; // Keep details button visible
                } else if (currentStatus === 'error') {
                    snapshotStatusText.textContent = 'Snapshot Error';
                    snapshotProgressBar.classList.add('bg-danger');
                    snapshotMessageText.textContent = data.error_message || 'An unknown error occurred.';
                    if (progressInterval) clearInterval(progressInterval);
                    if (viewDetailsBtn) viewDetailsBtn.style.display = 'inline-block'; // Keep details button visible
                } else { // Idle or pending
                    snapshotStatusText.textContent = 'Snapshot Idle';
                    snapshotProgressBar.classList.add('bg-primary'); // Or some other default
                    if (progressInterval) clearInterval(progressInterval);
                }
            })
            .catch(error => {
                console.error('Error fetching snapshot progress for index page:', error);
                if (snapshotMessageText) snapshotMessageText.textContent = 'Error fetching progress.';
                if (snapshotProgressBar) {
                    snapshotProgressBar.classList.remove('bg-primary', 'bg-success', 'progress-bar-animated', 'progress-bar-striped');
                    snapshotProgressBar.classList.add('bg-danger');
                    snapshotProgressBar.style.width = '100%';
                    snapshotProgressBar.textContent = 'Error';
                }
                if (snapshotStatusText) snapshotStatusText.textContent = 'Connection Error';
                const viewDetailsBtn = document.getElementById('viewProgressDetailsBtn');
                if (viewDetailsBtn) viewDetailsBtn.style.display = 'none';
                if (progressInterval) clearInterval(progressInterval);
            });
    }
});

/**
 * Initialize the cost trends chart
 */
function initCostTrendsChart() {
    // Get chart data from hidden input
    const trendsDataEl = document.getElementById('costTrendsData');
    if (!trendsDataEl) return;
    
    try {
        const trendsData = JSON.parse(trendsDataEl.value);
        const labels = trendsData.map(d => new Date(d.timestamp).toLocaleDateString());
        
        const ctx = document.getElementById('costTrendsChart').getContext('2d');
        const costTrendsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Storage Cost',
                        data: trendsData.map(d => d.total_storage_cost),
                        borderColor: 'rgba(54, 162, 235, 1)',
                        backgroundColor: 'rgba(54, 162, 235, 0.2)',
                        borderWidth: 2,
                        tension: 0.1
                    },
                    {
                        label: 'Download Cost',
                        data: trendsData.map(d => d.total_download_cost),
                        borderColor: 'rgba(255, 99, 132, 1)',
                        backgroundColor: 'rgba(255, 99, 132, 0.2)',
                        borderWidth: 2,
                        tension: 0.1
                    },
                    {
                        label: 'API Cost',
                        data: trendsData.map(d => d.total_api_cost),
                        borderColor: 'rgba(75, 192, 192, 1)',
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        borderWidth: 2,
                        tension: 0.1
                    },
                    {
                        label: 'Total Cost',
                        data: trendsData.map(d => d.total_cost),
                        borderColor: 'rgba(153, 102, 255, 1)',
                        backgroundColor: 'rgba(153, 102, 255, 0.2)',
                        borderWidth: 3,
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('en-US', {
                                        style: 'currency',
                                        currency: 'USD'
                                    }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return '$' + value.toFixed(2);
                            }
                        }
                    }
                }
            }
        });
    } catch (e) {
        console.error('Error initializing cost trends chart:', e);
    }
}

/**
 * Initialize the storage breakdown chart
 */
function initStorageBreakdownChart() {
    // Get bucket data from hidden input
    const bucketsDataEl = document.getElementById('bucketsData');
    if (!bucketsDataEl) return;
    
    try {
        const buckets = JSON.parse(bucketsDataEl.value);
        if (!buckets || buckets.length === 0) return;
        
        // Prepare chart data - use top 10 buckets by storage
        let topBuckets = [...buckets].sort((a, b) => b.storage_bytes - a.storage_bytes).slice(0, 10);
        
        // Calculate "Others" if there are more than 10 buckets
        if (buckets.length > 10) {
            const otherBuckets = buckets.slice(10);
            const otherBytes = otherBuckets.reduce((sum, bucket) => sum + bucket.storage_bytes, 0);
            topBuckets.push({
                name: 'Others',
                storage_bytes: otherBytes
            });
        }
        
        // Prepare data for chart
        const labels = topBuckets.map(b => b.name);
        const data = topBuckets.map(b => b.storage_bytes);
        
        // Create a color array
        const backgroundColors = [
            'rgba(54, 162, 235, 0.7)',
            'rgba(255, 99, 132, 0.7)',
            'rgba(75, 192, 192, 0.7)',
            'rgba(255, 159, 64, 0.7)',
            'rgba(153, 102, 255, 0.7)',
            'rgba(255, 205, 86, 0.7)',
            'rgba(201, 203, 207, 0.7)',
            'rgba(255, 99, 132, 0.5)',
            'rgba(54, 162, 235, 0.5)',
            'rgba(75, 192, 192, 0.5)',
            'rgba(100, 100, 100, 0.7)'
        ];
        
        const ctx = document.getElementById('storageBreakdownChart').getContext('2d');
        const storageChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: backgroundColors,
                    borderWidth: 1
                }]
            },
            options: {
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const bytes = context.raw;
                                const label = context.label;
                                
                                // Format bytes
                                let formattedBytes;
                                if (bytes >= 1099511627776) {
                                    formattedBytes = (bytes / 1099511627776).toFixed(2) + ' TB';
                                } else if (bytes >= 1073741824) {
                                    formattedBytes = (bytes / 1073741824).toFixed(2) + ' GB';
                                } else if (bytes >= 1048576) {
                                    formattedBytes = (bytes / 1048576).toFixed(2) + ' MB';
                                } else if (bytes >= 1024) {
                                    formattedBytes = (bytes / 1024).toFixed(2) + ' KB';
                                } else {
                                    formattedBytes = bytes + ' bytes';
                                }
                                
                                return label + ': ' + formattedBytes;
                            }
                        }
                    },
                    legend: {
                        position: 'bottom'
                    }
                },
                responsive: true
            }
        });
    } catch (e) {
        console.error('Error initializing storage breakdown chart:', e);
    }
}

/**
 * Generate a printable cost report
 */
function generateReport() {
    // Create a new window for the report
    const reportWindow = window.open('', '_blank', 'width=800,height=600');
    
    // Get snapshot data
    const snapshotDataEl = document.getElementById('snapshotData');
    if (!snapshotDataEl) {
        alert('No snapshot data available');
        reportWindow.close();
        return;
    }
    
    try {
        const snapshotData = JSON.parse(snapshotDataEl.value);
        const timestamp = new Date(snapshotData.timestamp).toLocaleString();
        
        // Build the report HTML
        let reportHtml = `
            <html>
            <head>
                <title>Backblaze Cost Report - ${timestamp}</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    h1 { color: #333; }
                    table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
                    th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
                    th { background-color: #f2f2f2; }
                    .total-row { font-weight: bold; background-color: #f8f9fa; }
                    .cost { text-align: right; }
                    .header { display: flex; justify-content: space-between; align-items: center; }
                    .section { margin-bottom: 30px; }
                    @media print {
                        .no-print { display: none; }
                        button { display: none; }
                    }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Backblaze Cost Report</h1>
                    <div>
                        <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
                        <p><strong>Snapshot Date:</strong> ${timestamp}</p>
                    </div>
                </div>
                
                <div class="section">
                    <h2>Summary</h2>
                    <table>
                        <tr>
                            <th>Category</th>
                            <th class="cost">Cost (USD)</th>
                            <th class="cost">Monthly Estimate (USD)</th>
                        </tr>
                        <tr>
                            <td>Storage</td>
                            <td class="cost">$${snapshotData.total_storage_cost.toFixed(2)}</td>
                            <td class="cost">$${(snapshotData.total_storage_cost * 30).toFixed(2)}</td>
                        </tr>
                        <tr>
                            <td>Downloads</td>
                            <td class="cost">$${snapshotData.total_download_cost.toFixed(2)}</td>
                            <td class="cost">$${(snapshotData.total_download_cost * 30).toFixed(2)}</td>
                        </tr>
                        <tr>
                            <td>API Transactions</td>
                            <td class="cost">$${snapshotData.total_api_cost.toFixed(2)}</td>
                            <td class="cost">$${(snapshotData.total_api_cost * 30).toFixed(2)}</td>
                        </tr>
                        <tr class="total-row">
                            <td>Total</td>
                            <td class="cost">$${snapshotData.total_cost.toFixed(2)}</td>
                            <td class="cost">$${(snapshotData.total_cost * 30).toFixed(2)}</td>
                        </tr>
                    </table>
                </div>
                
                <div class="section">
                    <h2>Bucket Breakdown</h2>
                    <table>
                        <tr>
                            <th>Bucket</th>
                            <th class="cost">Storage</th>
                            <th class="cost">Cost (USD)</th>
                            <th class="cost">% of Total</th>
                        </tr>`;
                        
        // Add bucket data
        for (const bucket of snapshotData.buckets) {
            const percentage = ((bucket.total_cost / snapshotData.total_cost) * 100).toFixed(1);
            const formattedSize = formatBytes(bucket.storage_bytes);
            
            reportHtml += `
                <tr>
                    <td>${bucket.name}</td>
                    <td class="cost">${formattedSize}</td>
                    <td class="cost">$${bucket.total_cost.toFixed(2)}</td>
                    <td class="cost">${percentage}%</td>
                </tr>`;
        }
        
        reportHtml += `
                    </table>
                </div>
                
                <div class="no-print" style="text-align: center; margin-top: 30px;">
                    <button onclick="window.print()">Print Report</button>
                    <button onclick="window.close()">Close</button>
                </div>
                
                <script>
                    // Format bytes function
                    function formatBytes(bytes) {
                        if (bytes >= 1099511627776) {
                            return (bytes / 1099511627776).toFixed(2) + ' TB';
                        } else if (bytes >= 1073741824) {
                            return (bytes / 1073741824).toFixed(2) + ' GB';
                        } else if (bytes >= 1048576) {
                            return (bytes / 1048576).toFixed(2) + ' MB';
                        } else if (bytes >= 1024) {
                            return (bytes / 1024).toFixed(2) + ' KB';
                        } else {
                            return bytes + ' bytes';
                        }
                    }
                </script>
            </body>
            </html>`;
        
        // Write the report to the new window
        reportWindow.document.write(reportHtml);
        reportWindow.document.close();
        
    } catch (e) {
        console.error('Error generating report:', e);
        reportWindow.document.write('<p>Error generating report. Please try again.</p>');
        reportWindow.document.close();
    }
}

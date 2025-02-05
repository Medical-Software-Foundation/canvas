growth_charts
=============

## Description

This plugin enables you to input observations, such as height, weight, etc., into growth charts provided by WHO and CDC. These charts are designed for children and adolescents and help determine their current percentile, which shows how their measurements compare to others of the same age and sex.

Users can toggle between the WHO and CDC charts, select their unit of measurement, and print from this plugin driven modal.

![growth-charts](/extensions/growth_charts/growth-charts.png)


To create these visualizations, we are using a template that accepts an array of the following parameters:

    data - file containing the main graph data (x, y, z)
    title - graph title
    xType -  type of data on the x-axis (Generic, Height, Length)
    yType - type of data on the x-axis (Generic, Height, Length)
    xLabel - label for the x-axis
    yLabel - label for the y-axis,
    zLabel - label for the z-axis,
    layerData - an array of objects (x, y) that will be plotted on the graph,
    tab - the tab to which the graph belongs (WHO, CDC),

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.


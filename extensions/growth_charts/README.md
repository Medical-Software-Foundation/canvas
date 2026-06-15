growth_charts
=============

## What it does

This plugin plots a child's height, weight, head circumference, BMI, and related measurements onto standard pediatric growth charts directly inside the patient chart. It reads the patient's recorded observations and draws their values against WHO and CDC reference curves so staff can see the patient's percentile at a glance. Users can switch between WHO and CDC charts, change the unit of measurement, and print the chart from the modal.

## Problem it solves

Tracking a child's growth against population norms usually means hand-plotting measurements on paper charts or jumping to an outside tool, then re-entering values to read a percentile. This plugin pulls the patient's existing observations and renders the curves in Canvas, removing the manual plotting and lookup.

## Who it's for

Pediatricians, family medicine clinicians, and nursing staff who track growth in children and adolescents during well-child and routine visits.

## How to install

```
canvas install growth_charts
```

## Configuration options

No configuration required.

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


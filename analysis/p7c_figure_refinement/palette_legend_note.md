# P7C palette and legend note

Continuous surfaces use viridis option D for occurrence probability and option C for full hurdle expected count, with shared limits across the five map weeks.
Support classes use the following colorblind-conscious semantic mapping:
- SUPPORTED: #009E73, green; predictor conditions well represented in training data
- CAUTION: #E69F00, orange; less well supported predictor conditions
- EXTRAPOLATIVE: #D55E00, vermilion; predictor conditions substantially outside training support

Support classes are not confidence intervals, direct correctness measures, or causal categories.
Map surfaces use ggplot2::geom_tile; boundaries use sf::geom_sf; scale bars and north arrows use ggspatial.

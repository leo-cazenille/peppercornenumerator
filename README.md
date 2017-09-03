# peppercornenumerator 

This package enumerates domain-level strand displacement (DSD) reaction
networks assuming low concentrations, where unimolecular reaction pathways
always complete before bimolecular reactions initiate. The enumerator considers
a diverse set of unimolecular and bimolecular reactions in order to account for
the fine-grained details that can happen on the sequence level. Currently
supported are: bind/unbind reactions, 3way-branch-migration and
4-way-branch-migration reactions and remote toehold migration. For more
background on reaction semantics we refer to the publication [Grun et al. (2014)].

## Installation
```bash
$ python setup.py install
```
or
```
$ python setup.py install --user
```

## Quickstart using the executable "peppercorn"

### Quickstart
Load the file `system.pil`, write results to `system-enum.pil`:

```sh
$ peppercorn -o system-enum.pil < system.pil
```

### Input/Output format

The following input format is recommended, as it provides exactly the
information the peppercornenumator can process. A number of other statements
may be provided, including sequence-level details, however they will be ignored
during enumeration and rate computation.

```
# This file describes the catalytically generated 3 arm junction 
# Yin et al. (2008)

# Domain Specifications 
length a = 6
length b = 6
length c = 6
length x = 6
length y = 6
length z = 6

# Initial Complex Specifiction (see kernel string format)
A = a x( b( y( z* c* ) ) ) 
B = b y( c( z( x* a* ) ) ) 
C = c z( a( x( y* b* ) ) ) 
ABC = a( x( b( y( z*( c*( y*( b*( x* + ) ) ) ) x*( a*( z*( c*( y* + ) ) ) ) ) ) ) ) z* 
I = y* b* x* a* 
```

```
$ peppercorn -o system-enum.pil < system.pil
```

```
# File generated by peppercorn-v0.5.0

# Domain Specifications 
length a = 6
length b = 6
length c = 6
length x = 6
length y = 6
length z = 6

# Resting-state Complexes 
A = a x( b( y( z* c* ) ) ) 
ABC = a( x( b( y( z*( c*( y*( b*( x* + ) ) ) ) x*( a*( z*( c*( y* + ) ) ) ) ) ) ) ) z* 
B = b y( c( z( x* a* ) ) ) 
C = c z( a( x( y* b* ) ) ) 
I = y* b* x* a* 

# Transient Complexes 
e1 = y* b* x* a*( + ) x( b( y( z* c* ) ) ) 
e5 = y*( b*( x*( a*( + ) ) ) ) z* c* y* b* x* 
e8 = b( y( c( z( x* a* ) ) ) + y* ) x* a* 
e12 = b( y( c( z( x* a* ) ) y* + ) ) x* a* 

# Detailed Reactions 
reaction [bind21         =      1.8e+06 /M/s ] B + I -> e8
reaction [branch-3way    =      18.5185 /s   ] e1 -> e5
reaction [open           =       1.4773 /s   ] e1 -> I + A
reaction [branch-3way    =    0.0303912 /s   ] e5 -> e1
reaction [open           =       1.4773 /s   ] e8 -> B + I
reaction [branch-3way    =      55.5556 /s   ] e8 -> e12
reaction [branch-3way    =      55.5556 /s   ] e12 -> e8
reaction [bind21         =      1.8e+06 /M/s ] I + A -> e1

```

## Version
0.5

## Authors
Karthik Sarma, Casey Grun, Stefan Badelt and Erik Winfree.


[Grun et al. (2014)]: <https://arxiv.org/abs/1505.03738>


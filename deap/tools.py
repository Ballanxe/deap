#    This file is part of DEAP.
#
#    DEAP is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of
#    the License, or (at your option) any later version.
#
#    DEAP is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with DEAP. If not, see <http://www.gnu.org/licenses/>.
"""The :mod:`~deap.tools` module contains the operators for evolutionary
algorithms. They are used to modify, select and move the individuals in their
environment. The set of operators it contains are readily usable in the
:class:`~deap.base.Toolbox`. In addition to the basic operators this module
also contains utility tools to enhance the basic algorithms with
:class:`Statistics`, :class:`HallOfFame`, :class:`Checkpoint`, and
:class:`History`.
"""
from __future__ import division
import bisect
import copy
import math
import random

try:
    import cPickle as pickle
except ImportError:
    import pickle

from functools import partial
from itertools import chain
from operator import attrgetter, eq
from collections import Sequence, defaultdict
from sys import stdout

def identity(obj):
    """Returns directly the argument *obj*.
    """
    return obj

def initRepeat(container, func, n):
    """Call the function *container* with a generator function corresponding
    to the calling *n* times the function *func*.
    
    :param container: The type to put in the data from func.
    :param func: The function that will be called n times to fill the
                 container.
    :param n: The number of times to repeat func.
    :returns: An instance of the container filled with data from func.
    
    This helper function can can be used in conjunction with a Toolbox 
    to register a generator of filled containers, as individuals or 
    population.
    
        >>> initRepeat(list, random.random, 2) # doctest: +ELLIPSIS, 
        ...                                    # doctest: +NORMALIZE_WHITESPACE
        [0.4761..., 0.6302...]

    See the :ref:`list-of-floats` and :ref:`population` tutorials for more examples.
    """
    return container(func() for _ in xrange(n))

def initIterate(container, generator):
    """Call the function *container* with an iterable as 
    its only argument. The iterable must be returned by 
    the method or the object *generator*.
    
    :param container: The type to put in the data from func.
    :param generator: A function returning an iterable (list, tuple, ...),
                      the content of this iterable will fill the container.
    :returns: An instance of the container filled with data from the
              generator.
    
    This helper function can can be used in conjunction with a Toolbox 
    to register a generator of filled containers, as individuals or 
    population.

        >>> from random import sample
        >>> from functools import partial
        >>> gen_idx = partial(sample, range(10), 10)
        >>> initIterate(list, gen_idx)
        [4, 5, 3, 6, 0, 9, 2, 7, 1, 8]

    See the :ref:`permutation` and :ref:`arithmetic-expr` tutorials for
    more examples.
    """
    return container(generator())

def initCycle(container, seq_func, n=1):
    """Call the function *container* with a generator function corresponding
    to the calling *n* times the functions present in *seq_func*.
    
    :param container: The type to put in the data from func.
    :param seq_func: A list of function objects to be called in order to
                     fill the container.
    :param n: Number of times to iterate through the list of functions.
    :returns: An instance of the container filled with data from the
              returned by the functions.
    
    This helper function can can be used in conjunction with a Toolbox 
    to register a generator of filled containers, as individuals or 
    population.
    
        >>> func_seq = [lambda:1 , lambda:'a', lambda:3]
        >>> initCycle(list, func_seq, n=2)
        [1, 'a', 3, 1, 'a', 3]

    See the :ref:`funky` tutorial for an example.
    """
    return container(func() for _ in xrange(n) for func in seq_func)

class History(object):
    """The :class:`History` class helps to build a genealogy of all the
    individuals produced in the evolution. It contains two attributes,
    the :attr:`genealogy_tree` that is a dictionary of lists indexed by
    individual, the list contain the indices of the parents. The second
    attribute :attr:`genealogy_history` contains every individual indexed
    by their individual number as in the genealogy tree.
    
    The produced genealogy tree is compatible with `NetworkX
    <http://networkx.lanl.gov/index.html>`_, here is how to plot the genealogy
    tree ::
    
        history = History()
        
        # Decorate the variation operators
        toolbox.decorate("mate", history.decorator)
        toolbox.decorate("mutate", history.decorator)
        
        # Create the population and populate the history
        population = toolbox.population(n=POPSIZE)
        history.update(population)
        
        # Do the evolution, the decorators will take care of updating the
        # history
        # [...]
        
        import matplotlib.pyplot as plt
        import networkx
        
        graph = networkx.DiGraph(history.genealogy_tree)
        graph = graph.reverse()     # Make the grah top-down
        colors = [toolbox.evaluate(history.genealogy_history[i])[0] for i in graph]
        networkx.draw(graph, node_color=colors)
        plt.show()
    
    Using NetworkX in combination with `pygraphviz
    <http://networkx.lanl.gov/pygraphviz/>`_ (dot layout) this amazing
    genealogy tree can be obtained from the OneMax example with a population
    size of 20 and 5 generations, where the color of the nodes indicate there
    fitness, blue is low and red is high.
    
    .. image:: /_images/genealogy.png
       :width: 67%
     
    .. note::
       The genealogy tree might get very big if your population and/or the 
       number of generation is large.
        
    """
    def __init__(self):
        self.genealogy_index = 0
        self.genealogy_history = dict()
        self.genealogy_tree = dict()
        
    def update(self, individuals):
        """Update the history with the new *individuals*. The index present in
        their :attr:`history_index` attribute will be used to locate their
        parents, it is then modified to a unique one to keep track of those
        new individuals. This method should be called on the individuals after
        each variation.
        
        :param individuals: The list of modified individuals that shall be
                            inserted in the history.
        
        If the *individuals* do not have a :attr:`history_index` attribute, 
        the attribute is added and this individual is considered as having no
        parent. This method should be called with the initial population to
        initialize the history.
        
        Modifying the internal :attr:`genealogy_index` of the history or the
        :attr:`history_index` of an individual may lead to unpredictable
        results and corruption of the history.
        """
        try:
            parent_indices = tuple(ind.history_index for ind in individuals)
        except AttributeError:
            parent_indices = tuple()
        
        for ind in individuals:
            self.genealogy_index += 1
            ind.history_index = self.genealogy_index
            self.genealogy_history[self.genealogy_index] = copy.deepcopy(ind)
            self.genealogy_tree[self.genealogy_index] = parent_indices
    
    @property
    def decorator(self):
        """Property that returns an appropriate decorator to enhance the
        operators of the toolbox. The returned decorator assumes that the
        individuals are returned by the operator. First the decorator calls
        the underlying operation and then calls the :func:`update` function
        with what has been returned by the operator. Finally, it returns the
        individuals with their history parameters modified according to the
        update function.
        """
        def decFunc(func):
            def wrapFunc(*args, **kargs):
                individuals = func(*args, **kargs)
                self.update(individuals)
                return individuals
            return wrapFunc
        return decFunc

    def getGenealogy(self, individual, max_depth=float("inf")):
        """Provide the genealogy tree of an *individual*. The individual must
        have an attribute :attr:`history_index` as defined by
        :func:`~deap.tools.History.update` in order to retrieve its associated
        genealogy tree. The returned graph contains the parents up to
        *max_depth* variations before this individual. If not provided
        the maximum depth is up to the begining of the evolution.

        :param individual: The individual at the root of the genealogy tree.
        :param max_depth: The approximate maximum distance between the root
                          (individual) and the leaves (parents), optional.
        :returns: A dictionary where each key is an individual index and the
                  values are a tuple corresponding to the index of the parents.
        """
        gtree = {}
        visited = set()     # Adds memory to the breadth first search
        def genealogy(index, depth):
            if index not in self.genealogy_tree:
                return             
            depth += 1
            if depth > max_depth:
                return
            parent_indices = self.genealogy_tree[index]
            gtree[index] = parent_indices
            for ind in parent_indices:
                if ind not in visited:
                    genealogy(ind, depth)
                visited.add(ind)
        genealogy(individual.history_index, 0)
        return gtree


class Checkpoint(object):
    """A checkpoint is a file containing the state of any object that has been
    hooked. While initializing a checkpoint, add the objects that you want to
    be dumped by appending keyword arguments to the initializer or using the 
    :meth:`add`. 

    In order to use efficiently this module, you must understand properly the
    assignment principles in Python. This module uses the *pointers* you passed
    to dump the object, for example the following won't work as desired ::

        >>> my_object = [1, 2, 3]
        >>> cp = Checkpoint()
        >>> cp.add("my_object", my_object)
        >>> my_object = [3, 5, 6]
        >>> cp.dump(open("example.ecp", "w"))
        >>> cp.load(open("example.ecp", "r"))
        >>> cp["my_object"]
        [1, 2, 3]

    In order to dump the new value of ``my_object`` it is needed to change its
    internal values directly and not touch the *label*, as in the following ::

        >>> my_object = [1, 2, 3]
        >>> cp = Checkpoint()
        >>> cp.add("my_object", my_object)
        >>> my_object[:] = [3, 5, 6]
        >>> cp.dump(open("example.ecp", "w"))
        >>> cp.load(open("example.ecp", "r"))
        >>> cp["my_object"]
        [3, 5, 6]

    """
    def __init__(self):
        self.objects = {}
        self.keys = {}
        self.values = {}

    def add(self, name, object, key=identity):
        """Add an object to the list of objects to be dumped. The object is
        added under the name specified by the argument *name*, the object
        added is *object*, and the *key* argument allow to specify a subpart
        of the object that should be dumped (*key* defaults to an identity key
        that dumps the entire object).
        
        :param name: The name under which the object will be dumped.
        :param object: The object to register for dumping.
        :param key: A function access the subcomponent of the object to dump,
                    optional.
        
        The following illustrates how to use the key.
        ::

            >>> from operator import itemgetter
            >>> my_object = [1, 2, 3]
            >>> cp = Checkpoint()
            >>> cp.add("item0", my_object, key=itemgetter(0))
            >>> cp.dump(open("example.ecp", "w"))
            >>> cp.load(open("example.ecp", "r"))
            >>> cp["item0"]
            1

        """
        self.objects[name] = object
        self.keys[name] = partial(key, object)

    def remove(self, *args):
        """Remove objects with the specified name from the list of objects to
        be dumped.
        
        :param name: The name of one or more object to remove from dumping.
        
        """
        for element in args:
            del self.objects[element]
            del self.keys[element]
            del self.values[element]

    def __getitem__(self, value):
        return self.values.get(value)

    def dump(self, file):
        """Dump the current registered object values in the provided
        *filestream*.
        
        :param filestream: A stream in which write the data.
        """
        self.values = dict.fromkeys(self.objects.iterkeys())
        for name, key in self.keys.iteritems():
            self.values[name] = key()
        pickle.dump(self.values, file)

    def load(self, file):
        """Load a checkpoint from the provided *filestream* retrieving the
        dumped object values, it is not safe to load a checkpoint file in a
        checkpoint object that contains references as all conflicting names
        will be updated with the new values.
        
        :param filestream: A stream from which to read a checkpoint.
        """
        self.values.update(pickle.load(file))

class Statistics(list):
    """Object that keeps record of statistics and key-value pair information
    computed during the evolution. When created the statistics object receives
    a *key* argument that is used to get the values on which the function will
    be computed. If not provided the *key* argument defaults to the identity 
    function.

    :param key: A function to access the values on which to compute the
                statistics, optional.

    Values can be retrieved via the *select* method given the appropriate
    key.
    ::
    
        >>> s = Statistics()
        >>> s.register("mean", mean)
        >>> s.register("max", max)
        >>> s.append([1, 2, 3, 4])
        >>> s.append([5, 6, 7, 8])
        >>> s.select("mean")
        [2.5, 6.5]
        >>> s.select("max")
        [4, 8]
        >>> s[-1]["mean"]
        6.5
        >>> mean, max_ = s.select("mean", "max")
        >>> mean[0]
        2.5
        >>> max_[0]
        4
    """
    def __init__(self, key=identity):
        self.key = key
        self.functions = {}
        
        self.header = None
        """Order of the columns to print when using the :meth:`stream` and
        :meth:`__str__` methods. The syntax is a single iterable containing
        string elements. For example, with the previously
        defined statistics class, one can print the generation and the
        fitness average, and maximum with
        ::

            s.header = ("gen", "mean", "max")
        
        If not set the header is built with all fields, in arbritrary order
        on insertion of the first data. The header can be removed by setting
        it to :data:`None`.
        """
        
        self.buffindex = 0

    def __getstate__(self):
        state = {}
        state['functions'] = self.functions
        state['header'] = self.header
        # Most key cannot be pickled in Python 2
        state['key'] = None
        return state

    def __setstate__(self, state):
        self.__init__(state['key'])
        self.functions = state['functions']
        self.header = state['header']

    def register(self, name, function, *args, **kargs):
        """Register a *function* that will be applied on the sequence each
        time :meth:`append` is called.

        :param name: The name of the statistics function as it would appear
                     in the dictionnary of the statistics object.
        :param function: A function that will compute the desired statistics
                         on the data as preprocessed by the key.
        :param argument: One or more argument (and keyword argument) to pass
                         automatically to the registered function when called,
                         optional.
        """        
        self.functions[name] = partial(function, *args, **kargs)

    def select(self, *names):
        """Return a list of values associated to the *names* provided
        in argument in each dictionary of the Statistics object list.
        One list per name is returned in order.
        ::

            >>> s = Statistics()
            >>> s.register("mean", numpy.mean)
            >>> s.register("max", numpy.mean)
            >>> s.append([1,2,3,4,5,6,7])
            >>> s.select("mean")
            [4.0]
            >>> s.select("mean", "max")
            ([4.0], [7.0])
        """
        if len(names) == 1:
            return [entry[names[0]] for entry in self]
        return tuple([entry[name] for entry in self] for name in names)

    def append(self, data=[], **kargs):
        """Apply to the input sequence *data* each registered function 
        and store the results plus the additional information from *kargs*
        in a dictionnary at the end of the list.
        
        :param data: Sequence of objects on which the statistics are computed.
        :param kargs: Additional key-value pairs to record.
        """
        if not self.key:
            raise AttributeError('It is required to set a key after unpickling a %s object.' % self.__class__.__name__)

        if not self.header:
            self.header = kargs.keys() + self.functions.keys()

        values = tuple(self.key(elem) for elem in data)
        
        entry = {}
        for key, func in self.functions.iteritems():
            entry[key] = func(values)
        entry.update(kargs)
        list.append(self, entry)
    
    def __delitem__(self, key):
        if isinstance(key, slice):
            for i, in range(*key.indices(len(self))):
                self._pop(i)
        else:
            self._pop(key)
        
    def _pop(self, index=0):
        """Retreive and delete element *index*. The header and stream will be
        adjusted to follow the modification.

        :param item: The index of the element to remove, optional. It defaults
                     to the first element.
        
        You can also use the following syntax to delete elements.
        ::
        
            del s[0]
            del s[1::5]
        """
        if index < self.buffindex:
            self.buffindex -= 1
        return super(self.__class__, self).pop(index)

    def setColumns(self, *args):
        """Set which columns will be outputed when calling converting
        the object to a string with `str` or using the stream property.
        The provided arguments must correspond to either the names of
        the registered functions or the keys of keyword arguments 
        provided when calling the append method.
        """
        self.header = args

    @property
    def stream(self):
        """Retrieve the formated unstreamed entries of the database including
        the headers.
        ::

            >>> s = Statistics()
            >>> s.append(gen=0)
            >>> print s.stream
            gen
              0
            >>> s.append(gen=1)
            >>> print s.stream
              1
        """
        startindex, self.buffindex = self.buffindex, len(self)
        return self.__str__(startindex)

    def __str__(self, startindex=0, columns=None):
        if not columns:
            columns = self.header
        columns_len = map(len, columns)

        str_matrix = []
        for line in self[startindex:]:
            str_line = []
            for i, name in enumerate(columns):
                value = line.get(name, "")
                string = "{:n}" if isinstance(value, float) else "{}"
                column = string.format(value)
                columns_len[i] = max(columns_len[i], len(column))
                str_line.append(column)
            str_matrix.append(str_line)
 
        template = "\t".join("{:<%i}" % i for i in columns_len)
        text = (template.format(*line) for line in str_matrix)
        if startindex == 0:
            text = chain([template.format(*columns)], text)
 
        return "\n".join(text)

class MultiStatistics(dict):
    """Dictionary of :class:`Statistics` object allowing to compute
    statistics on multiple keys using a single call to :meth:`append`. It
    takes a set of key-value pairs associating a statistics object to a
    unique name. This name can then be used to retrieve the statistics object.
    ::

        >>> stats1 = Statistics()
        >>> stats2 = Statistics(key=attrgetter("fitness.values"))
        >>> mstats = MultStatistics(genotype=stats1, fitness=stats2)
        >>> mstats.register("mean", numpy.mean, axis=0)
        >>> mstats.register("max", numpy.max)
        >>> mstats.append(pop, gen=0)
        >>> mstats['fitness'].select("mean")
        [5.0]
        >>> mstats['genotype'].select("max")
        [[1,0,0,0]]
        >>> stats1.select("max")
        [[1,0,0,0]]
    """
    def __init__(self, **kargs):
        for name, stats in kargs.items():
            self[name] = stats
        self.buffindex = 0
        self.columns = []

    def setColumns(self, *args):
        """Set which columns will be outputed when calling converting
        the object to a string with `str` or using the stream property.
        The provided arguments must correspond to either the names of
        keys provided during the init or the keys of keyword arguments 
        provided when calling the append method.
        """
        self.columns = args
        # self.is_key_column = True
        self.is_key_column = any(self.has_key(arg) for arg in args)
        
    def append(self, data=[], **kargs):
        """Calls :meth:`Statistics.append` with *data* and *kargs* on each
        :class:`Statistics` object.
        
        :param data: Sequence of objects on which the statistics are computed.
        :param kargs: Additional key-value pairs to record.
        """
        if not self.columns:
            args = self.keys()
            self.setColumns(*args)
        
        for stats in self.values():
            stats.append(data, **kargs)

    def register(self, name, function, *args, **kargs):
        """Register a *function* in each :class:`Statistics` object.
        
        :param name: The name of the statistics function as it would appear
                     in the dictionnary of the statistics object.
        :param function: A function that will compute the desired statistics
                         on the data as preprocessed by the key.
        :param argument: One or more argument (and keyword argument) to pass
                         automatically to the registered function when called,
                         optional.
        """
        for stats in self.values():
            stats.register(name, function, *args, **kargs)
    
    @property
    def stream(self):
        """Retrieve the formated unstreamed entries of the database including
        the headers. For the previous multi statistics object the result is
        ::

            >>> print mstats.stream
                    fitness                  genotype              
                   ---------    ------------------------------------
            gen    max  mean    max             mean
              0    6    5.0     [1, 1, 1, 0]    [0.5, 0.33, 0.75, 0]
            >>> mstats.append(pop, gen=1)
            >>> print mstats.stream
              1    8    5.5     [1, 1, 1, 1]    [0.75, 0.5, 1.0, 0.5]
        """
        startindex, self.buffindex = self.buffindex, len(self[self.keys()[0]])
        return self.__str__(startindex)

    def __str__(self, startindex=0):
        matrices = []
        first = next(self.itervalues())
        for column in self.columns:
            if self.has_key(column):
                stats = self[column]
                lines = stats.__str__(startindex).split('\n')
                length = max(len(line.expandtabs()) for line in lines)
                if startindex == 0:
                    lines.insert(0, "-" * length)
                    lines.insert(0, column.center(length))
            else:
                lines = first.__str__(startindex, (column,)).split('\n')
                length = max(len(line.expandtabs()) for line in lines)
                if startindex == 0 and self.is_key_column:
                    lines.insert(0, " " * length) 
                    lines.insert(0, " " * length)
            matrices.append(lines)

        text = ("\t".join(line) for line in zip(*matrices))
        return "\n".join(text)

class HallOfFame(object):
    """The hall of fame contains the best individual that ever lived in the
    population during the evolution. It is lexicographically sorted at all
    time so that the first element of the hall of fame is the individual that
    has the best first fitness value ever seen, according to the weights
    provided to the fitness at creation time.
    
    The insertion is made so that old individuals have priority on new
    individuals. A single copy of each individual is kept at all time, the
    equivalence between two individuals is made by the operator passed to the
    *similar* argument.

    :param maxsize: The maximum number of individual to keep in the hall of
                    fame.
    :param similar: An equivalence operator between two individuals, optional.
                    It defaults to operator :func:`operator.eq`.
    
    The class :class:`HallOfFame` provides an interface similar to a list
    (without being one completely). It is possible to retrieve its length, to
    iterate on it forward and backward and to get an item or a slice from it.
    """
    def __init__(self, maxsize, similar=eq):
        self.maxsize = maxsize
        self.keys = list()
        self.items = list()
        self.similar = similar
    
    def update(self, population):
        """Update the hall of fame with the *population* by replacing the
        worst individuals in it by the best individuals present in
        *population* (if they are better). The size of the hall of fame is
        kept constant.
        
        :param population: A list of individual with a fitness attribute to
                           update the hall of fame with.
        """
        if len(self) == 0 and self.maxsize !=0:
            # Working on an empty hall of fame is problematic for the
            # "for else"
            self.insert(population[0])
        
        for ind in population:
            if ind.fitness > self[-1].fitness or len(self) < self.maxsize:
                for hofer in self:
                    # Loop through the hall of fame to check for any
                    # similar individual
                    if self.similar(ind, hofer):
                        break
                else:
                    # The individual is unique and strictly better than
                    # the worst
                    if len(self) >= self.maxsize:
                        self.remove(-1)
                    self.insert(ind)
    
    def insert(self, item):
        """Insert a new individual in the hall of fame using the
        :func:`~bisect.bisect_right` function. The inserted individual is
        inserted on the right side of an equal individual. Inserting a new 
        individual in the hall of fame also preserve the hall of fame's order.
        This method **does not** check for the size of the hall of fame, in a
        way that inserting a new individual in a full hall of fame will not
        remove the worst individual to maintain a constant size.
        
        :param item: The individual with a fitness attribute to insert in the
                     hall of fame.
        """
        item = copy.deepcopy(item)
        i = bisect.bisect_right(self.keys, item.fitness)
        self.items.insert(len(self) - i, item)
        self.keys.insert(i, item.fitness)
    
    def remove(self, index):
        """Remove the specified *index* from the hall of fame.
        
        :param index: An integer giving which item to remove.
        """
        del self.keys[len(self) - (index % len(self) + 1)]
        del self.items[index]
    
    def clear(self):
        """Clear the hall of fame."""
        del self.items[:]
        del self.keys[:]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def __iter__(self):
        return iter(self.items)

    def __reversed__(self):
        return reversed(self.items)
    
    def __str__(self):
        return str(self.items)


class ParetoFront(HallOfFame):
    """The Pareto front hall of fame contains all the non-dominated individuals
    that ever lived in the population. That means that the Pareto front hall of
    fame can contain an infinity of different individuals.
    
    :param similar: A function that tels the Pareto front whether or not two
                    individuals are similar, optional.
    
    The size of the front may become very large if it is used for example on
    a continuous function with a continuous domain. In order to limit the number
    of individuals, it is possible to specify a similarity function that will
    return :data:`True` if the genotype of two individuals are similar. In that
    case only one of the two individuals will be added to the hall of fame. By
    default the similarity function is :func:`operator.__eq__`.
    
    Since, the Pareto front hall of fame inherits from the :class:`HallOfFame`, 
    it is sorted lexicographically at every moment.
    """
    def __init__(self, similar=eq):
        HallOfFame.__init__(self, None, similar)
    
    def update(self, population):
        """Update the Pareto front hall of fame with the *population* by adding 
        the individuals from the population that are not dominated by the hall
        of fame. If any individual in the hall of fame is dominated it is
        removed.
        
        :param population: A list of individual with a fitness attribute to
                           update the hall of fame with.
        """
        for ind in population:
            is_dominated = False
            has_twin = False
            to_remove = []
            for i, hofer in enumerate(self):    # hofer = hall of famer
                if hofer.fitness.dominates(ind.fitness):
                    is_dominated = True
                    break
                elif ind.fitness.dominates(hofer.fitness):
                    to_remove.append(i)
                elif ind.fitness == hofer.fitness and self.similar(ind, hofer):
                    has_twin = True
                    break
            
            for i in reversed(to_remove):       # Remove the dominated hofer
                self.remove(i)
            if not is_dominated and not has_twin:
                self.insert(ind)

######################################
# GA Crossovers                      #
######################################

def cxTwoPoints(ind1, ind2):
    """Execute a two points crossover on the input individuals. The two 
    individuals are modified in place and both keep their original length. 
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :returns: A tuple of two individuals.

    This function use the :func:`~random.randint` function from the python base
    :mod:`random` module.
    """
    size = min(len(ind1), len(ind2))
    cxpoint1 = random.randint(1, size)
    cxpoint2 = random.randint(1, size - 1)
    if cxpoint2 >= cxpoint1:
        cxpoint2 += 1
    else: # Swap the two cx points
        cxpoint1, cxpoint2 = cxpoint2, cxpoint1
   
    ind1[cxpoint1:cxpoint2], ind2[cxpoint1:cxpoint2] \
        = ind2[cxpoint1:cxpoint2], ind1[cxpoint1:cxpoint2]
        
    return ind1, ind2

def cxOnePoint(ind1, ind2):
    """Execute a one point crossover on the input individuals.
    The two individuals are modified in place. The resulting individuals will
    respectively have the length of the other.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :returns: A tuple of two individuals.

    This function use the :func:`~random.randint` function from the
    python base :mod:`random` module.
    """
    size = min(len(ind1), len(ind2))
    cxpoint = random.randint(1, size - 1)
    ind1[cxpoint:], ind2[cxpoint:] = ind2[cxpoint:], ind1[cxpoint:]
    
    return ind1, ind2

def cxUniform(ind1, ind2, indpb):
    """Execute a uniform crossover that modify in place the two individuals.
    The attributes are swapped according to the *indpb* probability.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :param indpb: Independent probabily for each attribute to be exchanged.
    :returns: A tuple of two individuals.
    
    This function use the :func:`~random.random` function from the python base
    :mod:`random` module.
    """
    size = min(len(ind1), len(ind2))    
    for i in xrange(size):
        if random.random() < indpb:
            ind1[i], ind2[i] = ind2[i], ind1[i]
    
    return ind1, ind2
    
def cxPartialyMatched(ind1, ind2):
    """Execute a partially matched crossover (PMX) on the input individuals.
    The two individuals are modified in place. This crossover expect iterable
    individuals of indices, the result for any other type of individuals is
    unpredictable.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :returns: A tuple of two individuals.

    Moreover, this crossover consists of generating two children by matching
    pairs of values in a certain range of the two parents and swapping the values
    of those indexes. For more details see [Goldberg1985]_.

    This function use the :func:`~random.randint` function from the python base
    :mod:`random` module.
    
    .. [Goldberg1985] Goldberg and Lingel, "Alleles, loci, and the traveling
       salesman problem", 1985.
    """
    size = min(len(ind1), len(ind2))
    p1, p2 = [0]*size, [0]*size

    # Initialize the position of each indices in the individuals
    for i in xrange(size):
        p1[ind1[i]] = i
        p2[ind2[i]] = i
    # Choose crossover points
    cxpoint1 = random.randint(0, size)
    cxpoint2 = random.randint(0, size - 1)
    if cxpoint2 >= cxpoint1:
        cxpoint2 += 1
    else: # Swap the two cx points
        cxpoint1, cxpoint2 = cxpoint2, cxpoint1
    
    # Apply crossover between cx points
    for i in xrange(cxpoint1, cxpoint2):
        # Keep track of the selected values
        temp1 = ind1[i]
        temp2 = ind2[i]
        # Swap the matched value
        ind1[i], ind1[p1[temp2]] = temp2, temp1
        ind2[i], ind2[p2[temp1]] = temp1, temp2
        # Position bookkeeping
        p1[temp1], p1[temp2] = p1[temp2], p1[temp1]
        p2[temp1], p2[temp2] = p2[temp2], p2[temp1]
    
    return ind1, ind2

def cxUniformPartialyMatched(ind1, ind2, indpb):
    """Execute a uniform partially matched crossover (UPMX) on the input
    individuals. The two individuals are modified in place. This crossover
    expect iterable individuals of indices, the result for any other type of
    individuals is unpredictable.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :returns: A tuple of two individuals.

    Moreover, this crossover consists of generating two children by matching
    pairs of values chosen at random with a probability of *indpb* in the two
    parents and swapping the values of those indexes. For more details see
    [Cicirello2000]_.

    This function use the :func:`~random.random` and :func:`~random.randint`
    functions from the python base :mod:`random` module.
    
    .. [Cicirello2000] Cicirello and Smith, "Modeling GA performance for
       control parameter optimization", 2000.
    """
    size = min(len(ind1), len(ind2))
    p1, p2 = [0]*size, [0]*size

    # Initialize the position of each indices in the individuals
    for i in xrange(size):
        p1[ind1[i]] = i
        p2[ind2[i]] = i
    
    for i in xrange(size):
        if random.random() < indpb:
            # Keep track of the selected values
            temp1 = ind1[i]
            temp2 = ind2[i]
            # Swap the matched value
            ind1[i], ind1[p1[temp2]] = temp2, temp1
            ind2[i], ind2[p2[temp1]] = temp1, temp2
            # Position bookkeeping
            p1[temp1], p1[temp2] = p1[temp2], p1[temp1]
            p2[temp1], p2[temp2] = p2[temp2], p2[temp1]
    
    return ind1, ind2

def cxOrdered(ind1, ind2):
    """Execute an ordered crossover (OX) on the input
    individuals. The two individuals are modified in place. This crossover
    expect iterable individuals of indices, the result for any other type of
    individuals is unpredictable.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :returns: A tuple of two individuals.

    Moreover, this crossover consists of generating holes in the input
    individuals. A hole is created when an attribute of an individual is
    between the two crossover points of the other individual. Then it rotates
    the element so that all holes are between the crossover points and fills
    them with the removed elements in order. For more details see
    [Goldberg1989]_.
    
    This function use the :func:`~random.sample` function from the python base
    :mod:`random` module.
    
    .. [Goldberg1989] Goldberg. Genetic algorithms in search, 
       optimization and machine learning. Addison Wesley, 1989
    """
    size = min(len(ind1), len(ind2))
    a, b = random.sample(xrange(size), 2)
    if a > b:
        a, b = b, a

    holes1, holes2 = [True]*size, [True]*size
    for i in range(size):
        if i < a or i > b:
            holes1[ind2[i]] = False
            holes2[ind1[i]] = False
    
    # We must keep the original values somewhere before scrambling everything
    temp1, temp2 = ind1, ind2
    k1 , k2 = b + 1, b + 1
    for i in range(size):
        if not holes1[temp1[(i + b + 1) % size]]:
            ind1[k1 % size] = temp1[(i + b + 1) % size]
            k1 += 1
        
        if not holes2[temp2[(i + b + 1) % size]]:
            ind2[k2 % size] = temp2[(i + b + 1) % size]
            k2 += 1
    
    # Swap the content between a and b (included)
    for i in range(a, b + 1):
        ind1[i], ind2[i] = ind2[i], ind1[i]
    
    return ind1, ind2

def cxBlend(ind1, ind2, alpha):
    """Executes a blend crossover that modify in-place the input individuals.
    The blend crossover expect individuals formed of a list of floating point
    numbers.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :param alpha: Extent of the interval in which the new values can be drawn
                  for each attribute on both side of the parents' attributes.
    :returns: A tuple of two individuals.
    
    This function use the :func:`~random.random` function from the python base
    :mod:`random` module.
    """
    for i, (x1, x2) in enumerate(zip(ind1, ind2)):
        gamma = (1. + 2. * alpha) * random.random() - alpha
        ind1[i] = (1. - gamma) * x1 + gamma * x2
        ind2[i] = gamma * x1 + (1. - gamma) * x2

    return ind1, ind2

def cxSimulatedBinary(ind1, ind2, eta):
    """Executes a simulated binary crossover that modify in-place the input
    individuals. The simulated binary crossover expect individuals formed of
    a list of floating point numbers.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :param eta: Crowding degree of the crossover. A high eta will produce
                children resembling to their parents, while a small eta will
                produce solutions much more different.
    :returns: A tuple of two individuals.
    
    This function use the :func:`~random.random` function from the python base
    :mod:`random` module.
    """
    for i, (x1, x2) in enumerate(zip(ind1, ind2)):
        rand = random.random()
        if rand <= 0.5:
            beta = 2. * rand
        else:
            beta = 1. / (2. * (1. - rand))
        beta **= 1. / (eta + 1.)
        ind1[i] = 0.5 * (((1 + beta) * x1) + ((1 - beta) * x2))
        ind2[i] = 0.5 * (((1 - beta) * x1) + ((1 + beta) * x2))
    
    return ind1, ind2


def cxSimulatedBinaryBounded(ind1, ind2, eta, low, up):
    """Executes a simulated binary crossover that modify in-place the input
    individuals. The simulated binary crossover expect individuals formed of
    a list of floating point numbers.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :param eta: Crowding degree of the crossover. A high eta will produce
                children resembling to their parents, while a small eta will
                produce solutions much more different.
    :param low: A value or a sequence of values that is the lower bound of the
                search space.
    :param up: A value or a sequence of values that is the upper bound of the
               search space.
    :returns: A tuple of two individuals.

    This function use the :func:`~random.random` function from the python base
    :mod:`random` module.

    .. note::
       This implementation is similar to the one implemented in the 
       original NSGA-II C code presented by Deb.
    """
    size = min(len(ind1), len(ind2))
    
    if not isinstance(low, Sequence):
        low = [low] * size
    if not isinstance(up, Sequence):
        up = [up] * size

    for i in xrange(size):
        if random.random() <= 0.5:
            # This epsilon should probably be changed for 0 since 
            # floating point arithmetic in Python is safer
            if abs(ind1[i] - ind2[i]) > 1e-14:
                x1 = min(ind1[i], ind2[i])
                x2 = max(ind1[i], ind2[i])
                xl = low[i]
                xu = up[i]
                rand = random.random()
                
                beta = 1.0 + (2.0 * (x1 - xl) / (x2 - x1))
                alpha = 2.0 - beta**-(eta + 1)
                if rand <= 1.0 / alpha:
                    beta_q = (rand * alpha)**(1.0 / (eta + 1))
                else:
                    beta_q = (1.0 / (2.0 - rand * alpha))**(1.0 / (eta + 1))
                
                c1 = 0.5 * (x1 + x2 - beta_q * (x2 - x1))
                
                beta = 1.0 + (2.0 * (xu - x2) / (x2 - x1))
                alpha = 2.0 - beta**-(eta + 1)
                if rand <= 1.0 / alpha:
                    beta_q = (rand * alpha)**(1.0 / (eta + 1))
                else:
                    beta_q = (1.0 / (2.0 - rand * alpha))**(1.0 / (eta + 1))
                c2 = 0.5 * (x1 + x2 + beta_q * (x2 - x1))
                
                c1 = min(max(c1, xl), xu)
                c2 = min(max(c2, xl), xu)
                
                if random.random() <= 0.5:
                    ind1[i] = c2
                    ind2[i] = c1
                else:
                    ind1[i] = c1
                    ind2[i] = c2
    
    return ind1, ind2   


######################################
# Messy Crossovers                   #
######################################

def cxMessyOnePoint(ind1, ind2):
    """Execute a one point crossover that will in most cases change the
    individuals size. The two individuals are modified in place.
    
    :param ind1: The first individual participating in the crossover.
    :param ind2: The second individual participating in the crossover.
    :returns: A tuple of two individuals.
    
    This function use the :func:`~random.randint` function from the python base
    :mod:`random` module.        
    """
    cxpoint1 = random.randint(0, len(ind1))
    cxpoint2 = random.randint(0, len(ind2))
    ind1[cxpoint1:], ind2[cxpoint2:] = ind2[cxpoint2:], ind1[cxpoint1:]
    
    return ind1, ind2
    
######################################
# ES Crossovers                      #
######################################

def cxESBlend(ind1, ind2, alpha):
    """Execute a blend crossover on both, the individual and the strategy. The
    individuals must have a :attr:`strategy` attribute. Adjustement of the
    minimal strategy shall be done after the call to this function, consider
    using a decorator.
    
    :param ind1: The first evolution strategy participating in the crossover.
    :param ind2: The second evolution strategy participating in the crossover.
    :param alpha: Extent of the interval in which the new values can be drawn
                  for each attribute on both side of the parents' attributes.
    :returns: A tuple of two evolution strategies.
    """
    for i, (x1, s1, x2, s2) in enumerate(zip(ind1, ind1.strategy, 
                                             ind2, ind2.strategy)):
        # Blend the values
        gamma = (1. + 2. * alpha) * random.random() - alpha
        ind1[i] = (1. - gamma) * x1 + gamma * x2
        ind2[i] = gamma * x1 + (1. - gamma) * x2
        # Blend the strategies
        gamma = (1. + 2. * alpha) * random.random() - alpha
        ind1.strategy[i] = (1. - gamma) * s1 + gamma * s2
        ind2.strategy[i] = gamma * s1 + (1. - gamma) * s2
    
    return ind1, ind2

def cxESTwoPoints(ind1, ind2):
    """Execute a classical two points crossover on both the individual and its
    strategy. The individuals must have a :attr:`strategy` attribute.The
    crossover points for the individual and the strategy are the same.
    
    :param ind1: The first evolution strategy participating in the crossover.
    :param ind2: The second evolution strategy participating in the crossover.
    :returns: A tuple of two evolution strategies.
    """
    size = min(len(ind1), len(ind2))
    
    pt1 = random.randint(1, size)
    pt2 = random.randint(1, size - 1)
    if pt2 >= pt1:
        pt2 += 1
    else: # Swap the two cx points
        pt1, pt2 = pt2, pt1
   
    ind1[pt1:pt2], ind2[pt1:pt2] = ind2[pt1:pt2], ind1[pt1:pt2]     
    ind1.strategy[pt1:pt2], ind2.strategy[pt1:pt2] = \
        ind2.strategy[pt1:pt2], ind1.strategy[pt1:pt2]
    
    return ind1, ind2

######################################
# GA Mutations                       #
######################################

def mutGaussian(individual, mu, sigma, indpb):
    """This function applies a gaussian mutation of mean *mu* and standard
    deviation *sigma* on the input individual. This mutation expects an
    iterable individual composed of real valued attributes. The *indpb*
    argument is the probability of each attribute to be mutated.
    
    :param individual: Individual to be mutated.
    :param mu: Mean around the individual of the mutation.
    :param sigma: Standard deviation of the mutation.
    :param indpb: Probability for each attribute to be mutated.
    :returns: A tuple of one individual.
    
    This function uses the :func:`~random.random` and :func:`~random.gauss`
    functions from the python base :mod:`random` module.
    """
    for i in xrange(len(individual)):
        if random.random() < indpb:
            individual[i] += random.gauss(mu, sigma)
    
    return individual,

def mutPolynomialBounded(individual, eta, low, up, indpb):
    """Polynomial mutation as implemented in original NSGA-II algorithm in
    C by Deb.
    
    :param individual: Individual to be mutated.
    :param eta: Crowding degree of the mutation. A high eta will produce
                a mutant resembling its parent, while a small eta will
                produce a solution much more different.
    :param low: A value or a sequence of values that is the lower bound of the
                search space.
    :param up: A value or a sequence of values that is the upper bound of the
               search space.
    :returns: A tuple of one individual.
    """
    size = len(individual)
    if not isinstance(low, Sequence):
        low = [low] * size
    if not isinstance(up, Sequence):
        up = [up] * size
    
    for i in xrange(size):
        if random.random() <= indpb:
            x = individual[i]
            xl = low[i]
            xu = up[i]
            delta_1 = (x - xl) / (xu - xl)
            delta_2 = (xu - x) / (xu - xl)
            rand = random.random()
            mut_pow = 1.0 / (eta + 1.)

            if rand < 0.5:
                xy = 1.0 - delta_1
                val = 2.0 * rand + (1.0 - 2.0 * rand) * xy**(eta + 1)
                delta_q = val**mut_pow - 1.0
            else:
                xy = 1.0 - delta_2
                val = 2.0 * (1.0 - rand) + 2.0 * (rand - 0.5) * xy**(eta + 1)
                delta_q = 1.0 - val**mut_pow

            x = x + delta_q * (xu - xl)
            x = min(max(x, xl), xu)
            individual[i] = x
    return individual,

def mutShuffleIndexes(individual, indpb):
    """Shuffle the attributes of the input individual and return the mutant.
    The *individual* is expected to be iterable. The *indpb* argument is the
    probability of each attribute to be moved. Usually this mutation is applied on 
    vector of indices.
    
    :param individual: Individual to be mutated.
    :param indpb: Probability for each attribute to be exchanged to another
                  position.
    :returns: A tuple of one individual.
    
    This function uses the :func:`~random.random` and :func:`~random.randint`
    functions from the python base :mod:`random` module.
    """
    size = len(individual)
    for i in xrange(size):
        if random.random() < indpb:
            swap_indx = random.randint(0, size - 2)
            if swap_indx >= i:
                swap_indx += 1
            individual[i], individual[swap_indx] = \
                individual[swap_indx], individual[i]
    
    return individual,

def mutFlipBit(individual, indpb):
    """Flip the value of the attributes of the input individual and return the
    mutant. The *individual* is expected to be iterable and the values of the
    attributes shall stay valid after the ``not`` operator is called on them.
    The *indpb* argument is the probability of each attribute to be
    flipped. This mutation is usually applied on boolean individuals.
    
    :param individual: Individual to be mutated.
    :param indpb: Probability for each attribute to be flipped.
    :returns: A tuple of one individual.
    
    This function uses the :func:`~random.random` function from the python base
    :mod:`random` module.
    """
    for indx in xrange(len(individual)):
        if random.random() < indpb:
            individual[indx] = type(individual[indx])(not individual[indx])
    
    return individual,

def mutUniformInt(individual, low, up, indpb):
    """Mutate an individual by replacing attributes, with probability *indpb*,
    by a integer uniformly drawn between *low* and *up* inclusively.
    
    :param low: The lower bound of the range from wich to draw the new
                integer.
    :param up: The upper bound of the range from wich to draw the new
                integer.
    :param indpb: Probability for each attribute to be mutated.
    :returns: A tuple of one individual.
    """
    for indx in xrange(len(individual)):
        if random.random() < indpb:
            individual[indx] = random.randint(low, up)
    
    return individual,


######################################
# ES Mutations                       #
######################################

def mutESLogNormal(individual, c, indpb):
    """Mutate an evolution strategy according to its :attr:`strategy`
    attribute as described in [Beyer2002]_. First the strategy is mutated
    according to an extended log normal rule, :math:`\\boldsymbol{\sigma}_t =
    \\exp(\\tau_0 \mathcal{N}_0(0, 1)) \\left[ \\sigma_{t-1, 1}\\exp(\\tau
    \mathcal{N}_1(0, 1)), \ldots, \\sigma_{t-1, n} \\exp(\\tau
    \mathcal{N}_n(0, 1))\\right]`, with :math:`\\tau_0 =
    \\frac{c}{\\sqrt{2n}}` and :math:`\\tau = \\frac{c}{\\sqrt{2\\sqrt{n}}}`,
    the the individual is mutated by a normal distribution of mean 0 and
    standard deviation of :math:`\\boldsymbol{\sigma}_{t}` (its current
    strategy) then . A recommended choice is ``c=1`` when using a :math:`(10,
    100)` evolution strategy [Beyer2002]_ [Schwefel1995]_.
    
    :param individual: Individual to be mutated.
    :param c: The learning parameter.
    :param indpb: Probability for each attribute to be flipped.
    :returns: A tuple of one individual.
    
    .. [Beyer2002] Beyer and Schwefel, 2002, Evolution strategies - A
       Comprehensive Introduction
       
    .. [Schwefel1995] Schwefel, 1995, Evolution and Optimum Seeking.
       Wiley, New York, NY
    """
    size = len(individual)
    t = c / math.sqrt(2. * math.sqrt(size))
    t0 = c / math.sqrt(2. * size)
    n = random.gauss(0, 1)
    t0_n = t0 * n
    
    for indx in xrange(size):
        if random.random() < indpb:
            individual.strategy[indx] *= math.exp(t0_n + t * random.gauss(0, 1))
            individual[indx] += individual.strategy[indx] * random.gauss(0, 1)
    
    return individual,
    

######################################
# Selections                         #
######################################

def selRandom(individuals, k):
    """Select *k* individuals at random from the input *individuals* with
    replacement. The list returned contains references to the input
    *individuals*.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list of selected individuals.
    
    This function uses the :func:`~random.choice` function from the
    python base :mod:`random` module.
    """
    return [random.choice(individuals) for i in xrange(k)]


def selBest(individuals, k):
    """Select the *k* best individuals among the input *individuals*. The
    list returned contains references to the input *individuals*.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list containing the k best individuals.
    """
    return sorted(individuals, key=attrgetter("fitness"), reverse=True)[:k]


def selWorst(individuals, k):
    """Select the *k* worst individuals among the input *individuals*. The
    list returned contains references to the input *individuals*.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list containing the k worst individuals.
    """
    return sorted(individuals, key=attrgetter("fitness"))[:k]


def selTournament(individuals, k, tournsize):
    """Select *k* individuals from the input *individuals* using *k*
    tournaments of *tournsize* individuals. The list returned contains
    references to the input *individuals*.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :param tournsize: The number of individuals participating in each tournament.
    :returns: A list of selected individuals.
    
    This function uses the :func:`~random.choice` function from the python base
    :mod:`random` module.
    """
    chosen = []
    for i in xrange(k):
        aspirants = selRandom(individuals, tournsize)
        chosen.append(max(aspirants, key=attrgetter("fitness")))
    return chosen

def selRoulette(individuals, k):
    """Select *k* individuals from the input *individuals* using *k*
    spins of a roulette. The selection is made by looking only at the first
    objective of each individual. The list returned contains references to
    the input *individuals*.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list of selected individuals.
    
    This function uses the :func:`~random.random` function from the python base
    :mod:`random` module.
    
    .. warning::
       The roulette selection by definition cannot be used for minimization 
       or when the fitness can be smaller or equal to 0.
    """
    s_inds = sorted(individuals, key=attrgetter("fitness"), reverse=True)
    sum_fits = sum(ind.fitness.values[0] for ind in individuals)
    
    chosen = []
    for i in xrange(k):
        u = random.random() * sum_fits
        sum_ = 0
        for ind in s_inds:
            sum_ += ind.fitness.values[0]
            if sum_ > u:
                chosen.append(ind)
                break
    
    return chosen


def selTournamentDCD(individuals, k):
    """Tournament selection based on dominance (D) between two individuals, if
    the two individuals do not interdominate the selection is made
    based on crowding distance (CD). The *individuals* sequence length has to
    be a multiple of 4. Starting from the beginning of the selected
    individuals, two consecutive individuals will be different (assuming all
    individuals in the input list are unique). Each individual from the input
    list won't be selected more than twice.
    
    This selection requires the individuals to have a :attr:`crowding_dist`
    attribute, which can be set by the :func:`assignCrowdingDist` function.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list of selected individuals.
    """
    def tourn(ind1, ind2):
        if ind1.fitness.dominates(ind2.fitness):
            return ind1
        elif ind2.fitness.dominates(ind1.fitness):
            return ind2

        if ind1.fitness.crowding_dist < ind2.fitness.crowding_dist:
            return ind2
        elif ind1.fitness.crowding_dist > ind2.fitness.crowding_dist:
            return ind1

        if random.random() <= 0.5:
            return ind1
        return ind2

    individuals_1 = random.sample(individuals, len(individuals))
    individuals_2 = random.sample(individuals, len(individuals))

    chosen = []
    for i in xrange(0, k, 4):
        chosen.append(tourn(individuals_1[i],   individuals_1[i+1]))
        chosen.append(tourn(individuals_1[i+2], individuals_1[i+3]))
        chosen.append(tourn(individuals_2[i],   individuals_2[i+1]))
        chosen.append(tourn(individuals_2[i+2], individuals_2[i+3]))

    return chosen
    

def selDoubleTournament(individuals, k, fitness_size, parsimony_size, fitness_first):
    """Tournament selection which use the size of the individuals in order
    to discriminate good solutions. This kind of tournament is obviously
    useless with fixed-length representation, but has been shown to
    significantly reduce excessive growth of individuals, especially in GP,
    where it can be used as a bloat control technique (see 
    [Luke2002fighting]_). This selection operator implements the double 
    tournament technique presented in this paper.
    
    The core principle is to use a normal tournament selection, but using a
    special sample function to select aspirants, which is another tournament
    based on the size of the individuals. To ensure that the selection
    pressure is not too high, the size of the size tournament (the number
    of candidates evaluated) can be a real number between 1 and 2. In this
    case, the smaller individual among two will be selected with a probability
    *size_tourn_size*/2. For instance, if *size_tourn_size* is set to 1.4,
    then the smaller individual will have a 0.7 probability to be selected.
    
    .. note::
        In GP, it has been shown that this operator produces better results
        when it is combined with some kind of a depth limit.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :param fitness_size: The number of individuals participating in each \
    fitness tournament
    :param parsimony_size: The number of individuals participating in each \
    size tournament. This value has to be a real number\
    in the range [1,2], see above for details.
    :param fitness_first: Set this to True if the first tournament done should \
    be the fitness one (i.e. the fitness tournament producing aspirants for \
    the size tournament). Setting it to False will behaves as the opposite \
    (size tournament feeding fitness tournaments with candidates). It has been \
    shown that this parameter does not have a significant effect in most cases\
    (see [Luke2002fighting]_).
    :returns: A list of selected individuals.
    
    .. [Luke2002fighting] Luke and Panait, 2002, Fighting bloat with 
        nonparametric parsimony pressure
    """
    assert (1 <= parsimony_size <= 2), "Parsimony tournament size has to be in the range [1, 2]."

    def _sizeTournament(individuals, k, select):
        chosen = []
        for i in xrange(k):
            # Select two individuals from the population
            # The first individual has to be the shortest
            prob = parsimony_size / 2.
            ind1, ind2 = select(individuals, k=2)

            if len(ind1) > len(ind2):
                ind1, ind2 = ind2, ind1
            elif len(ind1) == len(ind2):
                # random selection in case of a tie
                prob = 0.5

            # Since size1 <= size2 then ind1 is selected
            # with a probability prob
            chosen.append(ind1 if random.random() < prob else ind2)

        return chosen
    
    def _fitTournament(individuals, k, select):
        chosen = []
        for i in xrange(k):
            aspirants = select(individuals, k=fitness_size)
            chosen.append(max(aspirants, key=attrgetter("fitness")))
        return chosen
    
    if fitness_first:
        tfit = partial(_fitTournament, select=selRandom)
        return _sizeTournament(individuals, k, tfit)
    else:
        tsize = partial(_sizeTournament, select=selRandom)
        return _fitTournament(individuals, k, tsize)

######################################
# Non-Dominated Sorting   (NSGA-II)  #
######################################

def selNSGA2(individuals, k):
    """Apply NSGA-II selection operator on the *individuals*. Usually, the
    size of *individuals* will be larger than *k* because any individual
    present in *individuals* will appear in the returned list at most once.
    Having the size of *individuals* equals to *k* will have no effect other
    than sorting the population according to a non-domination scheme. The list
    returned contains references to the input *individuals*. For more details
    on the NSGA-II operator see [Deb2002]_.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list of selected individuals.
    
    .. [Deb2002] Deb, Pratab, Agarwal, and Meyarivan, "A fast elitist
       non-dominated sorting genetic algorithm for multi-objective
       optimization: NSGA-II", 2002.
    """
    pareto_fronts = sortNondominated(individuals, k)
    for front in pareto_fronts:
        assignCrowdingDist(front)
    
    chosen = list(chain(*pareto_fronts[:-1]))
    k = k - len(chosen)
    if k > 0:
        sorted_front = sorted(pareto_fronts[-1], key=attrgetter("fitness.crowding_dist"), reverse=True)
        chosen.extend(sorted_front[:k])
        
    return chosen

def sortNondominated(individuals, k, first_front_only=False):
    """Sort the first *k* *individuals* into different nondomination levels 
    using the "Fast Nondominated Sorting Approach" proposed by Deb et al.,
    see [Deb2002]_. This algorithm has a time complexity of :math:`O(MN^2)`, 
    where :math:`M` is the number of objectives and :math:`N` the number of 
    individuals.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :param first_front_only: If :obj:`True` sort only the first front and
                             exit.
    :returns: A list of Pareto fronts (lists), the first list includes 
              nondominated individuals.

    .. [Deb2002] Deb, Pratab, Agarwal, and Meyarivan, "A fast elitist
       non-dominated sorting genetic algorithm for multi-objective
       optimization: NSGA-II", 2002.
    """
    if k == 0:
        return []

    map_fit_ind = defaultdict(list)
    for ind in individuals:
        map_fit_ind[ind.fitness].append(ind)
    fits = map_fit_ind.keys()
    
    current_front = []
    next_front = []
    dominating_fits = defaultdict(int)
    dominated_fits = defaultdict(list)
    
    # Rank first Pareto front
    for i, fit_i in enumerate(fits):
        for fit_j in fits[i+1:]:
            if fit_i.dominates(fit_j):
                dominating_fits[fit_j] += 1
                dominated_fits[fit_i].append(fit_j)
            elif fit_j.dominates(fit_i):
                dominating_fits[fit_i] += 1
                dominated_fits[fit_j].append(fit_i)
        if dominating_fits[fit_i] == 0:
            current_front.append(fit_i)
    
    fronts = [[]]
    for fit in current_front:
        fronts[-1].extend(map_fit_ind[fit])
    pareto_sorted = len(fronts[-1])

    # Rank the next front until all individuals are sorted or 
    # the given number of individual are sorted.
    if not first_front_only:
        N = min(len(individuals), k)
        while pareto_sorted < N:
            fronts.append([])
            for fit_p in current_front:
                for fit_d in dominated_fits[fit_p]:
                    dominating_fits[fit_d] -= 1
                    if dominating_fits[fit_d] == 0:
                        next_front.append(fit_d)
                        pareto_sorted += len(map_fit_ind[fit_d])
                        fronts[-1].extend(map_fit_ind[fit_d])
            current_front = next_front
            next_front = []
    
    return fronts

def assignCrowdingDist(individuals):
    """Assign a crowding distance to each individual's fitness. The 
    crowding distance can be retrieve via the :attr:`crowding_dist` 
    attribute of each individual's fitness.
    """
    if len(individuals) == 0:
        return
    
    distances = [0.0] * len(individuals)
    crowd = [(ind.fitness.values, i) for i, ind in enumerate(individuals)]
    
    nobj = len(individuals[0].fitness.values)
    
    for i in xrange(nobj):
        crowd.sort(key=lambda element: element[0][i])
        distances[crowd[0][1]] = float("inf")
        distances[crowd[-1][1]] = float("inf")
        if crowd[-1][0][i] == crowd[0][0][i]:
            continue
        norm = nobj * float(crowd[-1][0][i] - crowd[0][0][i])
        for prev, cur, next in zip(crowd[:-2], crowd[1:-1], crowd[2:]):
            distances[cur[1]] += (next[0][i] - prev[0][i]) / norm

    for i, dist in enumerate(distances):
        individuals[i].fitness.crowding_dist = dist


######################################
# Strength Pareto         (SPEA-II)  #
######################################

def selSPEA2(individuals, k):
    """Apply SPEA-II selection operator on the *individuals*. Usually, the
    size of *individuals* will be larger than *n* because any individual
    present in *individuals* will appear in the returned list at most once.
    Having the size of *individuals* equals to *n* will have no effect other
    than sorting the population according to a strength Pareto scheme. The
    list returned contains references to the input *individuals*. For more
    details on the SPEA-II operator see [Zitzler2001]_.
    
    :param individuals: A list of individuals to select from.
    :param k: The number of individuals to select.
    :returns: A list of selected individuals.
    
    .. [Zitzler2001] Zitzler, Laumanns and Thiele, "SPEA 2: Improving the
       strength Pareto evolutionary algorithm", 2001.
    """
    N = len(individuals)
    L = len(individuals[0].fitness.values)
    K = math.sqrt(N)
    strength_fits = [0] * N
    fits = [0] * N
    dominating_inds = [list() for i in xrange(N)]
    
    for i, ind_i in enumerate(individuals):
        for j, ind_j in enumerate(individuals[i+1:], i+1):
            if ind_i.fitness.dominates(ind_j.fitness):
                strength_fits[i] += 1
                dominating_inds[j].append(i)
            elif ind_j.fitness.dominates(ind_i.fitness):
                strength_fits[j] += 1
                dominating_inds[i].append(j)
    
    for i in xrange(N):
        for j in dominating_inds[i]:
            fits[i] += strength_fits[j]
    
    # Choose all non-dominated individuals
    chosen_indices = [i for i in xrange(N) if fits[i] < 1]
    
    if len(chosen_indices) < k:     # The archive is too small
        for i in xrange(N):
            distances = [0.0] * N
            for j in xrange(i + 1, N):
                dist = 0.0
                for l in xrange(L):
                    val = individuals[i].fitness.values[l] - \
                          individuals[j].fitness.values[l]
                    dist += val * val
                distances[j] = dist
            kth_dist = _randomizedSelect(distances, 0, N - 1, K)
            density = 1.0 / (kth_dist + 2.0)
            fits[i] += density
            
        next_indices = [(fits[i], i) for i in xrange(N)
                        if not i in chosen_indices]
        next_indices.sort()
        #print next_indices
        chosen_indices += [i for _, i in next_indices[:k - len(chosen_indices)]]
                
    elif len(chosen_indices) > k:   # The archive is too large
        N = len(chosen_indices)
        distances = [[0.0] * N for i in xrange(N)]
        sorted_indices = [[0] * N for i in xrange(N)]
        for i in xrange(N):
            for j in xrange(i + 1, N):
                dist = 0.0
                for l in xrange(L):
                    val = individuals[chosen_indices[i]].fitness.values[l] - \
                          individuals[chosen_indices[j]].fitness.values[l]
                    dist += val * val
                distances[i][j] = dist
                distances[j][i] = dist
            distances[i][i] = -1
        
        # Insert sort is faster than quick sort for short arrays
        for i in xrange(N):
            for j in xrange(1, N):
                l = j
                while l > 0 and distances[i][j] < distances[i][sorted_indices[i][l - 1]]:
                    sorted_indices[i][l] = sorted_indices[i][l - 1]
                    l -= 1
                sorted_indices[i][l] = j
        
        size = N
        to_remove = []
        while size > k:
            # Search for minimal distance
            min_pos = 0
            for i in xrange(1, N):
                for j in xrange(1, size):
                    dist_i_sorted_j = distances[i][sorted_indices[i][j]]
                    dist_min_sorted_j = distances[min_pos][sorted_indices[min_pos][j]]
                    
                    if dist_i_sorted_j < dist_min_sorted_j:
                        min_pos = i
                        break
                    elif dist_i_sorted_j > dist_min_sorted_j:
                        break
            
            # Remove minimal distance from sorted_indices
            for i in xrange(N):
                distances[i][min_pos] = float("inf")
                distances[min_pos][i] = float("inf")
                
                for j in xrange(1, size - 1):
                    if sorted_indices[i][j] == min_pos:
                        sorted_indices[i][j] = sorted_indices[i][j + 1]
                        sorted_indices[i][j + 1] = min_pos
            
            # Remove corresponding individual from chosen_indices
            to_remove.append(min_pos)
            size -= 1
        
        for index in reversed(sorted(to_remove)):
            del chosen_indices[index]
    
    return [individuals[i] for i in chosen_indices]
    
def _randomizedSelect(array, begin, end, i):
    """Allows to select the ith smallest element from array without sorting it.
    Runtime is expected to be O(n).
    """
    if begin == end:
        return array[begin]
    q = _randomizedPartition(array, begin, end)
    k = q - begin + 1
    if i < k:
        return _randomizedSelect(array, begin, q, i)
    else:
        return _randomizedSelect(array, q + 1, end, i - k)

def _randomizedPartition(array, begin, end):
    i = random.randint(begin, end)
    array[begin], array[i] = array[i], array[begin]
    return _partition(array, begin, end)
    
def _partition(array, begin, end):
    x = array[begin]
    i = begin - 1
    j = end + 1
    while True:
        j -= 1
        while array[j] > x:
            j -= 1
        i += 1
        while array[i] < x:
            i += 1
        if i < j:
            array[i], array[j] = array[j], array[i]
        else:
            return j

######################################
# Replacement Strategies (ES)        #
######################################



######################################
# Migrations                         #
######################################

def migRing(populations, k, selection, replacement=None, migarray=None):
    """Perform a ring migration between the *populations*. The migration first
    select *k* emigrants from each population using the specified *selection*
    operator and then replace *k* individuals from the associated population
    in the *migarray* by the emigrants. If no *replacement* operator is
    specified, the immigrants will replace the emigrants of the population,
    otherwise, the immigrants will replace the individuals selected by the
    *replacement* operator. The migration array, if provided, shall contain
    each population's index once and only once. If no migration array is
    provided, it defaults to a serial ring migration (1 -- 2 -- ... -- n --
    1). Selection and replacement function are called using the signature
    ``selection(populations[i], k)`` and ``replacement(populations[i], k)``.
    It is important to note that the replacement strategy must select *k*
    **different** individuals. For example, using a traditional tournament for
    replacement strategy will thus give undesirable effects, two individuals
    will most likely try to enter the same slot.
    
    :param populations: A list of (sub-)populations on which to operate
                        migration.
    :param k: The number of individuals to migrate.
    :param selection: The function to use for selection.
    :param replacement: The function to use to select which individuals will
                        be replaced. If :obj:`None` (default) the individuals
                        that leave the population are directly replaced.
    :param migarray: A list of indices indicating where the individuals from 
                     a particular position in the list goes. This defaults
                     to a ring migration.
    """
    nbr_demes = len(populations)
    if migarray is None:
        migarray = range(1, nbr_demes) + [0]
    
    immigrants = [[] for i in xrange(nbr_demes)]
    emigrants = [[] for i in xrange(nbr_demes)]

    for from_deme in xrange(nbr_demes):
        emigrants[from_deme].extend(selection(populations[from_deme], k))
        if replacement is None:
            # If no replacement strategy is selected, replace those who migrate
            immigrants[from_deme] = emigrants[from_deme]
        else:
            # Else select those who will be replaced
            immigrants[from_deme].extend(replacement(populations[from_deme], k))

    for from_deme, to_deme in enumerate(migarray):
        for i, immigrant in enumerate(immigrants[to_deme]):
            indx = populations[to_deme].index(immigrant)
            populations[to_deme][indx] = emigrants[from_deme][i]
            
    
if __name__ == "__main__":
    import doctest
    
    random.seed(64)
    doctest.run_docstring_examples(initRepeat, globals())
    
    random.seed(64)
    doctest.run_docstring_examples(initIterate, globals())
    doctest.run_docstring_examples(initCycle, globals())
    
    doctest.run_docstring_examples(Statistics.register, globals())
    doctest.run_docstring_examples(Statistics.append, globals())

    doctest.run_docstring_examples(Checkpoint, globals())
    doctest.run_docstring_examples(Checkpoint.add, globals())
    

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import os
import sys

from spreadflow_core.config import config_eval
from spreadflow_core.dsl.parser import \
    AliasResolverPass, \
    ComponentsPurgePass, \
    ConnectionParser, \
    DescriptionParser, \
    LabelParser, \
    ParentParser, \
    PartitionBoundsPass, \
    PartitionControllersPass, \
    PartitionExpanderPass, \
    PartitionWorkerPass, \
    PortsValidatorPass
from spreadflow_core.dsl.stream import \
    AddTokenOp, \
    token_map
from spreadflow_core.dsl.tokens import \
    ConnectionToken, \
    ParentElementToken, \
    PartitionSelectToken
from graphviz import Digraph
from pprint import pformat

class DepthReductionPass(object):

    connection_parser = ConnectionParser()
    parent_parser = ParentParser()

    def __init__(self, maxdepth):
        self.maxdepth = maxdepth

    def __call__(self, stream):
        stream = self.connection_parser.divert(stream)
        stream = self.parent_parser.divert(stream)
        for op in stream: yield op

        node_depth = {}
        node_repl = {}
        for node, parent in self.parent_parser.get_parentmap_toposort():
            depth = 0 if parent is None else node_depth[parent] + 1
            node_depth[node] = depth

            if depth == self.maxdepth:
                node_repl[node] = node
            elif depth > self.maxdepth:
                node_repl[node] = node_repl[parent]

            if depth > 0 and depth <= self.maxdepth:
                yield AddTokenOp(ParentElementToken(node, parent))

        seen = set()
        for port_out, port_in in self.connection_parser.get_links():
            repl_port_out = node_repl.get(port_out, port_out)
            repl_port_in = node_repl.get(port_in, port_in)
            if repl_port_out is not repl_port_in:
                token = ConnectionToken(repl_port_out, repl_port_in)
                if not token in seen:
                    seen.add(token)
                    yield AddTokenOp(token)

class DepthReducedConnectionParser(ConnectionParser):
    """
    Extracts information about connected ports from a stream of operations.

    This is similar to ConnectionParser but it also allows connecting more than
    one input port to an output port.
    """

    def get_links(self):
        """
        Returns an iterator over output, input pairs
        """
        return token_map(self.selected).values()

class ConfvizCommand(object):

    path = None
    level = 1
    multiprocess = False
    partition = None

    connection_parser = DepthReducedConnectionParser()
    description_parser = DescriptionParser()
    label_parser = LabelParser()
    links_parser = DepthReducedConnectionParser()
    parent_parser = ParentParser()

    def __init__(self, out=sys.stdout):
        self._out = out

    def _strip_angle_brackets(self, text):
        while text.startswith('<') and text.endswith('>'):
            text = text[1:-1]
        return text

    def run(self, args):
        parser = argparse.ArgumentParser(prog=args[0])
        parser.add_argument('path', metavar='FILE',
                            help='Path to config file')
        parser.add_argument('-l', '--level', type=int,
                            help='Level of detail (0: toplevel components, default: 1)')
        parser.add_argument('-p', '--multiprocess', action='store_true',
                            help='Simulates multiprocess support, i.e., launch a separate process for each chain')
        parser.add_argument('--partition',
                            help='Simulates multiprocess support, select the given partition of the graph')

        parser.parse_args(args[1:], namespace=self)

        stream = config_eval(self.path)

        pipeline = list()
        pipeline.append(AliasResolverPass())
        pipeline.append(PortsValidatorPass())

        if self.multiprocess:
            pipeline.append(PartitionExpanderPass())
            pipeline.append(PartitionBoundsPass())
            if self.partition:
                pipeline.append(PartitionWorkerPass())
                partition = self.partition
                stream.append(AddTokenOp(PartitionSelectToken(partition)))
            else:
                pipeline.append(PartitionControllersPass())

        pipeline.append(ComponentsPurgePass())
        pipeline.append(DepthReductionPass(self.level))

        for compiler_step in pipeline:
            stream = compiler_step(stream)

        stream = self.connection_parser.extract(stream)
        stream = self.description_parser.extract(stream)
        stream = self.label_parser.extract(stream)
        stream = self.links_parser.extract(stream)
        stream = self.parent_parser.extract(stream)

        labels = self.label_parser.get_labelmap()
        descriptions = self.description_parser.get_descriptionmap()
        ports = self.connection_parser.get_portset()

        dg = Digraph(os.path.basename(self.path), engine='dot')

        # Walk the component trees from leaves to roots and build clusters.
        subgraphs = {}
        for child, parent in self.parent_parser.get_parentmap_toposort(reverse=True):
            if parent is not None:
                try:
                    sg = subgraphs[parent]
                except KeyError:
                    sg = Digraph('cluster_{:s}'.format(str(hash(parent))))
                    label = labels.get(parent, self._strip_angle_brackets(str(parent)))
                    tooltip = descriptions.get(parent, repr(parent) + "\n" + pformat(vars(parent)))
                    sg.attr('graph', label=label, tooltip=tooltip, color="blue")
                    subgraphs[parent] = sg

                if child in subgraphs:
                    child_sg = subgraphs.pop(child)
                    if child in ports:
                        # Place the port inside its own subgraph if a port is
                        # also the parent of other ports.
                        child_sg.node(str(hash(child)))
                    sg.subgraph(child_sg)
                elif child in ports:
                    sg.node(str(hash(child)))

        for sg in subgraphs.values():
            dg.subgraph(sg)

        # Edges
        for src, sink in self.links_parser.get_links():
            dg.edge(str(hash(src)), str(hash(sink)))

        # Tooltips
        for n in ports:
            try:
                tooltip = descriptions.get(n, repr(n) + "\n" + pformat(vars(n)))
            except TypeError:
                tooltip = ''
            label = labels.get(n, self._strip_angle_brackets(str(n)))
            dg.node(str(hash(n)), label=label, tooltip=tooltip)

        print(dg.pipe(format='svg'), file=self._out)
        return 0

def main():
    cmd = ConfvizCommand()
    sys.exit(cmd.run(sys.argv))

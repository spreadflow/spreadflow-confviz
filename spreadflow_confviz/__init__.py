from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from spreadflow_core import graph
from spreadflow_core.config import config_eval
from spreadflow_core.component import PortCollection
from spreadflow_core.dsl.parser import \
    AliasResolverPass, \
    ComponentsPurgePass, \
    EventHandlersPass, \
    PartitionBoundsPass, \
    PartitionControllersPass, \
    PartitionExpanderPass, \
    PartitionWorkerPass, \
    PortsValidatorPass, \
    portmap
from spreadflow_core.dsl.stream import \
    AddTokenOp, \
    stream_extract, \
    token_attr_map
from spreadflow_core.dsl.tokens import \
    ComponentToken, \
    ConnectionToken, \
    DescriptionToken, \
    LabelToken, \
    PartitionSelectToken
from graphviz import Digraph
from pprint import pformat
from toposort import toposort

import sys
import argparse
import os

class ConfvizCommand(object):

    path = None
    level = 1
    multiprocess = False
    partition = None

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

        is_port_collection = lambda c: isinstance(c, PortCollection)

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
        pipeline.append(EventHandlersPass())

        for compiler_step in pipeline:
            stream = compiler_step(stream)

        connection_ops, stream = stream_extract(stream, ConnectionToken)
        connections = list(portmap(connection_ops).items())

        component_ops, stream = stream_extract(stream, ComponentToken)
        components = list(token_attr_map(component_ops, 'element'))

        label_ops, stream = stream_extract(stream, LabelToken)
        labels = token_attr_map(label_ops, 'element', 'label')

        description_ops, stream = stream_extract(stream, DescriptionToken)
        descriptions = token_attr_map(description_ops, 'element', 'description')

        outs, ins = zip(*connections)

        # Build up parent-child relationships.
        comp_tree = []
        for comp in set(list(ins) + list(outs) + list(components)):
            if is_port_collection(comp):
                for subcomp in set(comp.ins + comp.outs):
                    if comp is not subcomp:
                        comp_tree.append((comp, subcomp))
            else:
                comp_tree.append((comp, None))

        children = graph.digraph(comp_tree)
        parents = graph.reverse(children)
        levels = list(toposort(parents))

        self.level = min(self.level, len(levels))

        # Pretend that components at the specified level are fully connected.
        extra_links = []
        if self.level < len(levels):
            for comp in levels[self.level]:
                if is_port_collection(comp):
                    for port_in in comp.ins:
                        for port_out in comp.outs:
                            if port_in is not port_out:
                                extra_links.append((port_in, port_out))

        # Build up the flow graph.
        g = graph.digraph(connections + extra_links)
        rg = graph.reverse(g)

        # Only show ports at the specified level if they have a connection to
        # ports with another parent.
        ignorable_comps = set()
        if self.level < len(levels):
            for comp in levels[self.level]:
                if not is_port_collection(comp):
                    my_parents = parents.get(comp, [])
                    conns = g.get(comp, set()).union(rg.get(comp, set()))
                    for peer in conns:
                        if my_parents != parents.get(peer):
                            break
                    else:
                        # Ignore this port if it has no peers or all of them a have the
                        # same parent.
                        ignorable_comps.add(comp)

        # Ignore everything which is beyond the specified level.
        for comps in levels[self.level+1:]:
            ignorable_comps.update(comps)


        # Perform the graph contraction.
        g = graph.contract(g, lambda n: n not in ignorable_comps)

        dg = Digraph(os.path.basename(self.path), engine='dot')

        # Build clusters wrapping port collections.
        subgraphs = {}
        visible_ports = set(ins + outs)
        for level in reversed(levels[:self.level]):
            for c in level:
                if is_port_collection(c):
                    ports = set(c.ins + c.outs).intersection(visible_ports)
                    if len(ports) == 0:
                        continue

                    sg = Digraph('cluster_{:s}'.format(str(hash(c))))
                    label = labels.get(c, self._strip_angle_brackets(str(c)))
                    tooltip = descriptions.get(c, repr(c) + "\n" + pformat(vars(c)))
                    sg.attr('graph', label=label, tooltip=tooltip, color="blue")

                    for port in ports:
                        if port not in ignorable_comps:
                            sg.node(str(hash(port)))
                        if port in subgraphs:
                            sg.subgraph(subgraphs.pop(port))

                    subgraphs[c] = sg

        for sg in subgraphs.values():
            dg.subgraph(sg)

        # Edges
        for src, sinks in g.items():
            for sink in sinks:
                dg.edge(str(hash(src)), str(hash(sink)))

        # Tooltips
        for n in graph.vertices(g):
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

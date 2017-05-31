""" Additional functions missing in the OSMnx package"""

import os.path
import pickle

import geopandas as gpd
import networkx as nx
import osmnx as ox
import shapely.geometry as geom
import shapely.ops as ops

from . import propagation as prop
from . import utils


def load_network(place, which_result=1, overwrite=False, tolerance=0):
    """Generates streets and buildings"""

    # Generate filenames
    file_prefix = 'data/{}'.format(utils.string_to_filename(place))
    filename_data_streets = 'data/{}_streets.pickle'.format(
        utils.string_to_filename(place))
    filename_data_boundary = 'data/{}_boundary.pickle'.format(
        utils.string_to_filename(place))
    filename_data_wave = 'data/{}_wave.pickle'.format(
        utils.string_to_filename(place))
    filename_data_buildings = 'data/{}_buildings.pickle'.format(
        utils.string_to_filename(place))

    # Create the output directory if it does not exist
    if not os.path.isdir('data/'):
        os.mkdirs('data/')

    if not overwrite and \
            os.path.isfile(filename_data_streets) and \
            os.path.isfile(filename_data_buildings) and \
            os.path.isfile(filename_data_boundary):
        # Load from file
        time_start = utils.debug(None, 'Loading data from disk')
        data = load_place(file_prefix, tolerance=tolerance)
    else:
        # Load from internet
        time_start = utils.debug(None, 'Loading data from the internet')
        data = download_place(place, which_result=which_result, tolerance=tolerance)

    graph_streets = data['streets']
    gdf_buildings = data['buildings']
    gdf_boundary = data['boundary']
    add_geometry(graph_streets)

    utils.debug(time_start)

    # Generate wave propagation graph:
    # Vehicles are placed in a undirected version of the graph because electromagnetic
    # waves do not respect driving directions
    if not overwrite and os.path.isfile(filename_data_wave):
        # Load from file
        time_start = utils.debug(None, 'Loading graph for wave propagation')
        with open(filename_data_wave, 'rb') as file:
            graph_streets_wave = pickle.load(file)
    else:
        # Generate
        time_start = utils.debug(None, 'Generating graph for wave propagation')
        graph_streets_wave = graph_streets.to_undirected()
        prop.add_edges_if_los(graph_streets_wave, gdf_buildings)
        with open(filename_data_wave, 'wb') as file:
            pickle.dump(graph_streets_wave, file)

    utils.debug(time_start)

    network = {'graph_streets': graph_streets,
               'graph_streets_wave': graph_streets_wave,
               'gdf_buildings': gdf_buildings,
               'gdf_boundary': gdf_boundary}

    return network


def download_place(place, network_type='drive', file_prefix=None, which_result=1, project=True, tolerance=0):
    """ Downloads streets and buildings for a place, saves the data to disk and returns them """

    if file_prefix is None:
        file_prefix = 'data/{}'.format(utils.string_to_filename(place))

    if which_result is None:
        which_result = which_result_polygon(place)

    # Streets
    streets = ox.graph_from_place(
        place, network_type=network_type, which_result=which_result)
    if project:
        streets = ox.project_graph(streets)
    filename_streets = '{}_streets.pickle'.format(file_prefix)
    with open(filename_streets, 'wb') as file:
        pickle.dump(streets, file)

    # Boundary and buildings
    boundary = ox.gdf_from_place(place, which_result=which_result)
    polygon = boundary['geometry'].iloc[0]
    buildings = ox.create_buildings_gdf(polygon)
    if project:
        buildings = ox.project_gdf(buildings)
        boundary = ox.project_gdf(boundary)

    # Save buildings
    filename_buildings = '{}_buildings.pickle'.format(file_prefix)
    with open(filename_buildings, 'wb') as file:
        pickle.dump(buildings, file)

    # Build and save simplified buildings
    if tolerance != 0:
        filename_buildings_simpl = '{}_buildings_{:.2f}.pickle'.format(file_prefix, tolerance)
        buildings = simplify_buildings(buildings)
        with open(filename_buildings_simpl, 'wb') as file:
            pickle.dump(buildings, file)

    # Save boundary
    filename_boundary = '{}_boundary.pickle'.format(file_prefix)
    with open(filename_boundary, 'wb') as file:
        pickle.dump(boundary, file)

    # Return data
    data = {'streets': streets, 'buildings': buildings, 'boundary': boundary}
    return data


def load_place(file_prefix, tolerance=0):
    """ Loads previously downloaded street and building data of a place"""

    filename_buildings = '{}_buildings.pickle'.format(file_prefix)

    if tolerance == 0:
        with open(filename_buildings, 'rb') as file:
            buildings = pickle.load(file)
    else:
        filename_buildings_simpl = '{}_buildings_{:.2f}.pickle'.format(file_prefix, tolerance)
        if os.path.isfile(filename_buildings_simpl):
            with open(filename_buildings_simpl, 'rb') as file:
                buildings = pickle.load(file)
        else:
            with open(filename_buildings, 'rb') as file:
                buildings_compl = pickle.load(file)
                buildings = simplify_buildings(buildings_compl)
            with open(filename_buildings_simpl, 'wb') as file:
                pickle.dump(buildings, file)

    filename_streets = '{}_streets.pickle'.format(file_prefix)
    with open(filename_streets, 'rb') as file:
        streets = pickle.load(file)

    filename_boundary = '{}_boundary.pickle'.format(file_prefix)
    with open(filename_boundary, 'rb') as file:
        boundary = pickle.load(file)

    place = {'streets': streets, 'buildings': buildings, 'boundary': boundary}
    return place


def add_geometry(streets):
    """ Adds geometry object to the edges of the graph where they are missing"""
    for u_node, v_node, data in streets.edges(data=True):
        if 'geometry' not in data:
            coord_x1 = streets.node[u_node]['x']
            coord_y1 = streets.node[u_node]['y']
            coord_x2 = streets.node[v_node]['x']
            coord_y2 = streets.node[v_node]['y']
            data['geometry'] = geom.LineString(
                [(coord_x1, coord_y1), (coord_x2, coord_y2)])


def check_geometry(streets):
    """ Checks if all edges of the graph have a geometry object"""

    complete = True
    for _, _, data in streets.edges(data=True):
        if 'geometry' not in data:
            complete = False
            break

    return complete


def line_route_between_nodes(node_from, node_to, graph):
    """Determines the line representing the shortest path between two nodes"""

    route = nx.shortest_path(graph, node_from, node_to, weight='length')
    edge_nodes = list(zip(route[:-1], route[1:]))
    lines = []
    for u_node, v_node in edge_nodes:
        # If there are parallel edges, select the shortest in length
        data = min([data for data in graph.edge[u_node][v_node].values()],
                   key=lambda x: x['length'])
        lines.append(data['geometry'])

    line = ops.linemerge(lines)
    return line


def which_result_polygon(query, limit=5):
    """Determines the first which_result value that returns a polygon from the nominatim API"""

    response = ox.osm_polygon_download(query, limit=limit, polygon_geojson=1)
    for index, result in enumerate(response):
        if result['geojson']['type'] == 'Polygon':
            return index + 1
    return None


def simplify_buildings(gdf_buildings, tolerance=1):
    """Simplifies the building polygons by reducing the number of edges"""

    geoms_list = gdf_buildings.geometry.tolist()
    geoms_list_comb = []
    count_buildings = len(geoms_list)

    # Merge polygons
    for idx1, geom1 in enumerate(geoms_list):

        if geom1 is None:
            continue
        elif not isinstance(geom1, geom.Polygon):
            geoms_list_comb.append(geom1)
            continue

        # NOTE: because of previous merges we need to check from the beginning and not from idx+1
        for idx2, geom2 in enumerate(geoms_list):

            if idx1 == idx2:
                continue

            if not isinstance(geom2, geom.Polygon):
                continue

            dist = geom1.distance(geom2)

            if dist > tolerance:
                continue

            buffer = dist / 2 * 2  # TODO: why factor 2 needed?
            geom1_buf = geom1.buffer(buffer)
            geom2_buf = geom2.buffer(buffer)

            if not geom1_buf.intersects(geom2_buf):
                continue

            # TODO: not ideal method!
            geom_union = ops.unary_union([geom1_buf, geom2_buf]).buffer(-buffer)

            # If the union is 2 seperate polygon we keep them otherwise we save the union
            if not isinstance(geom_union, geom.MultiPolygon):  # TODO: why does this even happen?
                geom1 = geom_union
                geoms_list[idx2] = None

        geoms_list[idx1] = geom1
        geoms_list_comb.append(geom1)

    # Remove interiors of polygons
    geoms_list_ext = []
    for geometry in geoms_list_comb:
        if not isinstance(geometry, geom.Polygon):
            geoms_list_ext.append(geometry)
        else:
            poly_simp = geom.Polygon(geometry.exterior)
            geoms_list_ext.append(poly_simp)

    # TODO: whole section has no effect?
    # Simplify polygons
    geoms_list_simpl = []
    for geometry in geoms_list_ext:
        if not isinstance(geometry, geom.Polygon):
            geoms_list_simpl.append(geometry)
            continue

        geometry_simpl = geometry.simplify(tolerance, preserve_topology=False)

        # TODO: still a bug here!

        if isinstance(geometry_simpl, geom.MultiPolygon):
            # TODO: why does this happen? fix
            # for poly in geometry_simpl:
            #     if not poly.is_empty:
            #         geoms_list_simpl.append(poly)
            geoms_list_simpl.append(geometry)
        else:
            if not geometry_simpl.is_empty:
                geoms_list_simpl.append(geometry_simpl)  # TODO: why does this happen?
            else:
                geoms_list_simpl.append(geometry)

    # Build a new GDF
    buildings = {}
    for idx, geometry in enumerate(geoms_list_simpl):
        building = {'id': idx,
                    'geometry': geometry}
        buildings[idx] = building

    gdf_buildings_opt = gpd.GeoDataFrame(buildings).T

    return gdf_buildings_opt
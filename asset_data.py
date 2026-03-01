import bpy
from resonitelink.models.assets.mesh.raw_data import TriangleSubmeshRawData
from resonitelink.models.datamodel import *
from .interop import *

def collectMeshData(mesh : bpy.types.Mesh):

    hasTangents = False
    # tangent calculation only works for tris and quads, also it needs a UV map
    if not any(poly.loop_total < 3 or poly.loop_total > 4 for poly in mesh.polygons) and len(mesh.uv_layers) > 0:
        hasTangents = True
        mesh.calc_tangents()

    # Get all UV Sets
    uv_layers = mesh.uv_layers
    
    # Get vertex color attributes (Limited to the first color group)
    vertex_colors = -1
    vertex_color_domain = 'CORNER'  # Default domain
    if (hasattr(mesh, 'color_attributes')):
        # New way with color attributes
        if (len(mesh.color_attributes) > 0):
            vertex_colors = mesh.color_attributes[0]
            vertex_color_domain = vertex_colors.domain
    else:
        # Old way with vertex colors
        if (len(mesh.vertex_colors) > 0):
            vertex_colors = mesh.vertex_colors

    # Save a dictionary of unique vertex hashes for fast indexing
    v_map = {}  # TODO: Make hashing faster probably
    idmax = 0   # Current maximum vertex ID
    
    # Create output lists
    verts = []  # Position data of each vertex (replicated)
    colors = []  # Currently limited to 1 color attribute per vertex
    normals = []  # Normals per vertex
    tangents = []  # Tangents per vertex
    uvs = [[] for _ in uv_layers]  # List of uv lists per uv set
    submeshes = []  # List of lists of triangle indices, per material

    # Loop through all triangles and store their indices according
    # to their material ID
    tris : list[bpy.types.MeshLoopTriangle] = mesh.loop_triangles
    tri_map = {}  # A dictionary of material ID mapped to triangle indices
    for tri in tris:
        # Get the material ID for this triangle
        mat_id = mesh.polygons[tri.polygon_index].material_index
        
        # If the current material doesn't exist in the map add it
        if (mat_id not in tri_map):
            tri_map[mat_id] = []
        
        # Get loop indices
        tri_loops = tri.loops
        
        # Append triangles to the submesh map (reverse winding order)
        for loop_idx in reversed(tri_loops):
            # Extract vertex information
            vidx = mesh.loops[loop_idx].vertex_index
            vpos = mesh.vertices[vidx].co
            vnor = mesh.loops[loop_idx].normal
            vuvs = [(layer.name, layer.data[loop_idx].uv) for layer in uv_layers]
            vtan = mesh.loops[loop_idx].tangent
            vcol = None
            if (vertex_colors != -1):
                # Check the domain of the color attribute before assignment
                col_idx = vidx if (vertex_color_domain == 'POINT') else loop_idx
                vcol = vertex_colors.data[col_idx].color
            
            # Construct a unique hash for the vertex
            vhash = (
                int(vidx),
                (vnor.x, vnor.y, vnor.z),
                tuple((name, uv.x, uv.y) for name, uv in vuvs),
                (vcol[0], vcol[1], vcol[2], vcol[3]) if (vertex_colors != -1) else None,
                (vtan.x, vtan.y, vtan.z) if hasTangents else None
            )
            
            # Check if the vertex exists uniquely and get its id
            v_tid = -1
            if (not vhash in v_map):
                # Store the new index
                v_map[vhash] = idmax
                v_tid = idmax
                idmax = idmax + 1
                
                # Store new data for this vertex
                verts.append(Float3(
                        *b2u_coords(vpos.x, vpos.y, vpos.z)
                ))
                if (vertex_colors != -1):
                    colors.append(Color(
                        vcol[0], vcol[1], vcol[2], vcol[3]
                    ))
                normals.append(Float3(
                    *b2u_coords(vnor[0], vnor[1], vnor[2])
                ))
                if hasTangents:
                    tangents.append(Float4(
                        *b2u_coords(*vtan), -mesh.loops[loop_idx].bitangent_sign
                    ))
                for uid, layer in enumerate(vuvs):
                    uvs[uid].append(layer[1][0])
                    uvs[uid].append(layer[1][1])
            else:
                # Retrieve the old index
                v_tid = v_map[vhash]
            
            # Append the vertex index to the triangle map
            tri_map[mat_id].append(v_tid)
    
    # Expand the triangle map into a list of lists (sorted by material id)
    for mid in sorted(tri_map):
        submeshes.append(tri_map[mid])
    
    # TODO: Extract material information

    return {
        'positions': verts,
        'submeshes': [
            TriangleSubmeshRawData(len(tri_indicies)//3, tri_indicies) for tri_indicies in submeshes
        ],
        'colors': colors if (vertex_colors != -1) else None,
        'normals': normals,
        'uv_channel_dimensions': [2 for _ in uvs],  # Hard coded to U, V (2D)
        'uvs': uvs,
        'tangents': tangents if hasTangents else None
    }
# Blender Imports
import logging
from typing import Any

import bpy
from mathutils import Euler

# Resonitelink Imports
from resonitelink.models.datamodel import *
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink import ResoniteLinkWebsocketClient, TriangleSubmeshRawData
from resonitelink.exceptions import ResoniteLinkException

import threading

#from .asset_data import *

class ID_SlotData():

    idToSlotData : dict[bpy.types.ID, 'ID_SlotData'] = {}
    lock = threading.Lock()

    def __init__(self, id : bpy.types.ID):
        self.id : bpy.types.ID = id
        self.slot : SlotProxy = None

    @classmethod
    def Get(cls, id : bpy.types.ID) -> 'ID_SlotData':
        ID_SlotData.lock.acquire()
        res = ID_SlotData.idToSlotData.get(id, None)
        ID_SlotData.lock.release()
        return res
        
    @classmethod
    def Remove(cls, id : bpy.types.ID):
        ID_SlotData.lock.acquire()
        ID_SlotData.idToSlotData.pop(id)
        ID_SlotData.lock.release()

    @classmethod
    def Clear(cls):
        ID_SlotData.lock.acquire()
        ID_SlotData.idToSlotData = {}
        ID_SlotData.lock.release()

    @classmethod
    def Add(cls, id : bpy.types.ID, idSlotData : ID_SlotData):
        ID_SlotData.lock.acquire()
        ID_SlotData.idToSlotData[id] = idSlotData
        ID_SlotData.lock.release()

    # can be overriden if derived classes need more control over the creation of the slot
    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        self.slot = await client.add_slot(
                name=self.id.name,
                tag=self.id.id_type
            )
    
    # can be overriden if derived classes need more control over the updating of the slot
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await client.update_slot(
                    self.slot,
                    name=self.id.name,
                    tag=self.id.id_type
                )
        

class AssetSlotData(ID_SlotData):

    assetsSlotRoot : SlotProxy = None

    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().instantiateAsync(client, context)
        assetsSlotRoot = await AssetSlotData.getAssetsSlotRootAsync(client, context)
        await client.update_slot(
            slot=self.slot,
            parent=assetsSlotRoot
        )
        
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().updateAsync(client, context)
        assetsSlotRoot = await AssetSlotData.getAssetsSlotRootAsync(client, context)
        await client.update_slot(
            slot=self.slot,
            parent=assetsSlotRoot
        )

    @classmethod
    async def getAssetsSlotRootAsync(cls, client : ResoniteLinkWebsocketClient, context : bpy.types.Context) -> SlotProxy:
        if AssetSlotData.assetsSlotRoot is None:
            AssetSlotData.assetsSlotRoot = await client.add_slot(
                name="Assets",
                parent=SceneSlotData.Get(context.scene).slot
            )
        else:
            try:
                await client.update_slot(
                    AssetSlotData.assetsSlotRoot,
                    name="Assets",
                    parent=SceneSlotData.Get(context.scene).slot
                )
            except:
                AssetSlotData.assetsSlotRoot = None
                return await AssetSlotData.getAssetsSlotRootAsync(client, context)

        return AssetSlotData.assetsSlotRoot


class MaterialAssetSlotData(AssetSlotData):

    defaultMaterial : ComponentProxy = None

    def __init__(self, mat : bpy.types.Material):
        super().__init__(mat)
        
    @classmethod
    def Get(cls, mat : bpy.types.Material) -> 'MaterialAssetSlotData':
        return super().Get(mat)
    
    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().instantiateAsync(client, context)
        color = self.findNodeValue("Base Color") # ShaderNodeBsdfPrincipled
        color = (1,1,1,1) if color is None else color
        self.matComp = await self.slot.add_component(
            "[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic",
            AlbedoColor=Field_ColorX(value=ColorX(color[0], color[1], color[2], color[3], "Linear"))
        )
        
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().updateAsync(client, context)
        color = self.findNodeValue("Base Color") # ShaderNodeBsdfPrincipled
        color = (1,1,1,1) if color is None else color
        await self.matComp.update_members(
            AlbedoColor=Field_ColorX(value=ColorX(color[0], color[1], color[2], color[3], "Linear"))
        )
    
    def findNodeValue(self, nodeName : str) -> Any:
        mat : bpy.types.Material = self.id
        for node in mat.node_tree.nodes: # https://docs.blender.org/api/current/bpy.types.ShaderNode.html#shadernode-nodeinternal
            for input in node.inputs:
                if input.name == nodeName:
                    return input.default_value
        return None
    
    @classmethod
    async def AddDefaultMaterialAsync(cls, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        if MaterialAssetSlotData.defaultMaterial is None:
            assetsSlot = await AssetSlotData.getAssetsSlotRootAsync(client, context)
            defaultMatSlot = await client.add_slot(
                name="Default Material (Debug)",
                parent=assetsSlot
            )
            matComp = await defaultMatSlot.add_component("[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic")
            MaterialAssetSlotData.defaultMaterial = matComp

class MeshAssetSlotData(AssetSlotData):

    def __init__(self, mesh : bpy.types.Mesh):
        super().__init__(mesh)
        self.meshComp : ComponentProxy = None
        
    @classmethod
    def Get(cls, mesh : bpy.types.Mesh) -> 'MeshAssetSlotData':
        return super().Get(mesh)
    
    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().instantiateAsync(client, context)
        assetUrl = await self.getMeshUrlAsync(client, context)
        self.meshComp = await self.slot.add_component(
            "[FrooxEngine]FrooxEngine.StaticMesh",
            URL=Field_Uri(value=assetUrl)
        )
        
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().updateAsync(client, context)
        assetUrl = await self.getMeshUrlAsync(client, context)
        await self.meshComp.update_members(
            URL=Field_Uri(value=assetUrl)
        )

    async def getMeshUrlAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context) -> str:
        meshData = self.collectMeshData()

        # Import the raw mesh data into Resonite
        asset_url = await client.import_mesh_raw_data(**meshData)

        return asset_url
    
    def collectMeshData(self):

        mesh : bpy.types.Mesh = self.id

        # Calculate custom normals
        if (hasattr(mesh, 'calc_normals_split')):
            # Old method (4.0)
            mesh.calc_normals_split()
        else:
            # TODO: New method
            #mesh.customdata_custom_splitnormals_add()
            pass

        # Triangulate the evaluated mesh
        mesh.calc_loop_triangles()
        
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
        
        # Clean up data
        if (hasattr(mesh, 'calc_normals_split')):
            mesh.free_normals_split()
        else:
            # mesh.customdata_custom_splitnormals_clear()
            pass
        
        if hasTangents:
            mesh.free_tangents()

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
    

class ObjectSlotData(ID_SlotData):

    def __init__(self, obj : bpy.types.Object):
        super().__init__(obj)

    @classmethod
    def Get(cls, obj : bpy.types.Object) -> 'ObjectSlotData':
        return super().Get(obj)
        
    def getSlotKwargs(self, context : bpy.types.Context) -> dict[str, Any]:
        obj : bpy.types.Object = self.id
        parentSlotData = ObjectSlotData.Get(obj.parent) if obj.parent is not None else SceneSlotData.Get(context.scene)
        localPos = obj.matrix_local.translation.to_tuple()
        euler = obj.matrix_local.to_euler("XZY")
        localRotQ = b2u_euler2quaternion(euler)
        localScale = obj.matrix_local.to_scale().to_tuple() # could use obj.scale here which seems to preserve negative scale
        return {'name': obj.name,
                'position': Float3(*b2u_coords(*localPos)),
                'rotation': FloatQ(localRotQ.x, localRotQ.y, localRotQ.z, localRotQ.w),
                'scale': Float3(*b2u_scale(*localScale)),
                'tag': obj.type,
                'parent': parentSlotData.slot}
    
    async def ensureParentExistsAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        obj : bpy.types.Object = self.id
        if obj.parent is not None:
            par = ObjectSlotData.Get(obj.parent)
            if par is None:
                par = ObjectSlotData(obj.parent)
                ID_SlotData.Add(obj.parent, par)
                await par.instantiateAsync(client, context)
            else:
                try:
                    await par.updateAsync(client, context)
                except:
                    # slot was probably deleted
                    await par.instantiateAsync(client, context)
    
    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await self.ensureParentExistsAsync(client, context)
        self.slot = await client.add_slot(
            **self.getSlotKwargs(context)
        )
        
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await self.ensureParentExistsAsync(client, context)
        await client.update_slot(
            slot=self.slot,
            **self.getSlotKwargs(context)
        )

    # def toMeshData(self) -> MeshObjectSlotData:
    #     meshObjectSlotData = MeshObjectSlotData(self.id)
    #     meshObjectSlotData.slot = self.slot
    #     return meshObjectSlotData


class MeshObjectSlotData(ObjectSlotData):

    def __init__(self, obj : bpy.types.Object):
        super().__init__(obj)
        self.meshData : MeshAssetSlotData = None
        self.matData : list[MaterialAssetSlotData] = [] 
        self.meshRenderer : ComponentProxy = None
        self.hidden = False

    @classmethod
    def Get(cls, obj : bpy.types.Object) -> 'MeshObjectSlotData':
        res = super().Get(obj)
        # if isinstance(res, MeshObjectSlotData):
        #     return res
        return res

    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):

        await super().instantiateAsync(client, context)

        matRefList = [
            Reference(
                target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>",
                target_id=matData.matComp.id
            ) for matData in self.matData
        ]

        if len(matRefList) == 0:
            if MaterialAssetSlotData.defaultMaterial == None:
                await MaterialAssetSlotData.AddDefaultMaterialAsync(client, context)
            matRefList = [
                Reference(
                    target_id=MaterialAssetSlotData.defaultMaterial.id,
                    target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>"
                )
            ]

        self.meshRenderer = await self.slot.add_component(
            "[FrooxEngine]FrooxEngine.MeshRenderer",
            Mesh=Reference(
                target_id=self.meshData.meshComp.id,
                target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"
            ),
            Materials=SyncList(
                *matRefList
            ),
            Enabled=Field_Bool(value=not self.hidden)
        )
    
    # ToDo: make this accept a Mesh as parameter and generate the asset uri internally
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().updateAsync(client, context)

        matRefList = [
            Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>",
                    target_id=matData.matComp.id
            ) for matData in self.matData
        ]

        if len(matRefList) == 0:
            if MaterialAssetSlotData.defaultMaterial == None:
                await MaterialAssetSlotData.AddDefaultMaterialAsync(client, context)
            matRefList = [
                Reference(
                    target_id=MaterialAssetSlotData.defaultMaterial.id,
                    target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>"
                )
            ]

        await self.meshRenderer.update_members(
            Mesh=Reference(
                target_id=self.meshData.meshComp.id,
                target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Mesh>"
            ),
            Materials=SyncList(
                *matRefList
            ),
            Enabled=Field_Bool(value=not self.hidden)
        )

    async def addOrUpdateMaterialAsync(self, mat : bpy.types.Material, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        matSlotData = MaterialAssetSlotData.Get(mat)
        if matSlotData is None:
            matSlotData = MaterialAssetSlotData(mat)
            ID_SlotData.Add(mat, matSlotData)
            await matSlotData.instantiateAsync(client, context)
        else:
            try:
                await matSlotData.updateAsync(client, context)
            except: 
                await matSlotData.instantiateAsync(client, context)
        
        self.matData.append(matSlotData)
    
    async def addOrUpdateMeshAsync(self, mesh : bpy.types.Mesh, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        meshSlotData = MeshAssetSlotData.Get(mesh)
        if meshSlotData is None:
            meshSlotData = MeshAssetSlotData(mesh)
            ID_SlotData.Add(mesh, meshSlotData)
            await meshSlotData.instantiateAsync(client, context)
        else:
            try:
                await meshSlotData.updateAsync(client, context)
            except: 
                await meshSlotData.instantiateAsync(client, context)
        
        self.meshData = meshSlotData
        

class SceneSlotData(ID_SlotData):

    @classmethod
    def Get(cls, scene : bpy.types.Scene) -> 'SceneSlotData':
        return super().Get(scene)


def b2u_coords(x, y, z):
    """
    Convert Blender coordinates to Unity coordinates.
    
    Parameters
    ----------
    x : float
        The Blender x coordinate
    y : float
        The Blender y coordinate
    z : float
        The Blender z coordinate
    
    Returns
    -------
    x : float
        The converted Unity x coordinate
    y : float
        The converted Unity y coordinate
    z : float
        The converted Unity z coordinate
    """
    
    #return -x, -z, y
    return -x, z, -y

def b2u_scale(x, y, z):
    """
    Convert Blender scales to Unity scales.
    
    Parameters
    ----------
    x : float
        The Blender x scale
    y : float
        The Blender y scale
    z : float
        The Blender z scale
    
    Returns
    -------
    x : float
        The converted Unity x scale
    y : float
        The converted Unity y scale
    z : float
        The converted Unity z scale
    """
    
    return x, z, y

def b2u_euler2quaternion(e):
    """
    Convert Blender Euler rotation to Unity quaternion.
    
    Parameters
    ----------
    e : mathutils.Euler
        The input Blender euler rotation
    
    Returns
    -------
    q : Quaternion
        The output Unity quaternion
    """
    
    return Euler((e.x, -e.z, e.y), "XYZ").to_quaternion()
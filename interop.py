# Blender Imports
from typing import Any

import bpy
from mathutils import Euler

# Resonitelink Imports
from resonitelink.models.datamodel import *
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink import ResoniteLinkWebsocketClient
from resonitelink.exceptions import ResoniteLinkException

import threading

class ID_SlotData():

    idToSlotData : dict[bpy.types.ID, 'ID_SlotData'] = {}
    lock = threading.Lock()

    def __init__(self, id : bpy.types.ID):
        self.id : bpy.types.ID = id
        self.slot : SlotProxy = None
        ID_SlotData.Add(self.id, self)

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
    def Add(cls, id : bpy.types.ID, idSlotData : ID_SlotData):
        ID_SlotData.lock.acquire()
        ID_SlotData.idToSlotData[id] = idSlotData
        ID_SlotData.lock.release()

    # can be overriden if derived classes need more control over the creation of the slot
    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        self.slot = await client.add_slot(
                name=self.id.name,
                position=Float3(0, 0, 0),
                rotation=FloatQ(0, 0, 0, 1),
                scale=Float3(1, 1, 1),
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
            except ResoniteLinkException:
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
        color = self.findBaseColor()
        self.matComp = await self.slot.add_component(
            "[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic",
            AlbedoColor=Field_ColorX(value=ColorX(color[0], color[1], color[2], color[3]))
        )
        
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await super().updateAsync(client, context)
        color = self.findBaseColor()
        self.matComp.update_members(
            AlbedoColor=Field_ColorX(value=ColorX(color[0], color[1], color[2], color[3]))
        )
    
    def findBaseColor(self):
        mat : bpy.types.Material = self.id
        for node in mat.node_tree.nodes:
            for input in node.inputs:
                if input.name == "Base Color":
                    return input.default_value
        return (1,1,1,1)
    
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

# class MeshAssetSlotData(AssetSlotData):

#     def __init__(self, mesh : bpy.types.Mesh):
#         super().__init__(mesh)
#         self.meshComp : ComponentProxy = None
        
#     @classmethod
#     def Get(cls, mesh : bpy.types.Mesh) -> 'MeshAssetSlotData':
#         return super().Get(mesh)
    
#     async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
#         await super().instantiateAsync(client, context)
#         mesh : bpy.types.Mesh = self.id
#         self.meshComp = await self.slot.add_component(
#             "[FrooxEngine]FrooxEngine.StaticMesh",
#             URL=Field_Uri(value="")
#         )
        
#     async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
#         await super().updateAsync(client, context)
#         mat : bpy.types.Material = self.id
#         self.matComp.update_members(
#             AlbedoColor=ColorX(mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], mat.diffuse_color[3])
#         )
    

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
        if obj.parent is not None and ObjectSlotData.Get(obj.parent) is None:
            await ObjectSlotData(obj.parent).instantiateAsync(client, context)
    
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


class MeshObjectSlotData(ObjectSlotData):

    def __init__(self, obj : bpy.types.Object):
        super().__init__(obj)
        self.meshComp : ComponentProxy = None
        self.matData : list[MaterialAssetSlotData] = [] 
        self.meshRenderer : ComponentProxy = None
        self.hidden = False
        self.assetUrl = ""

    @classmethod
    def Get(cls, obj : bpy.types.Object) -> 'MeshObjectSlotData':
        return super().Get(obj)

    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        if self.slot is None:
            await super().instantiateAsync(client, context)

        if len(self.matData) == 0 and MaterialAssetSlotData.defaultMaterial == None:
            await MaterialAssetSlotData.AddDefaultMaterialAsync(client, context)

        self.meshComp = await self.slot.add_component(
            "[FrooxEngine]FrooxEngine.StaticMesh",
            URL=Field_Uri(value=self.assetUrl)
        )
        matRefList = [
            Reference(
                target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>",
                target_id=matData.matComp.id
            ) for matData in self.matData
        ]
        if len(matRefList) == 0:
            matRefList = [
                Reference(
                    target_id=MaterialAssetSlotData.defaultMaterial.id,
                    target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>"
                )
            ]
        self.meshRenderer = await self.slot.add_component(
            "[FrooxEngine]FrooxEngine.MeshRenderer",
            Mesh=Reference(
                target_id=self.meshComp.id,
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

        if len(self.matData) == 0 and MaterialAssetSlotData.defaultMaterial == None:
            await MaterialAssetSlotData.AddDefaultMaterialAsync(client, context)

        await self.meshComp.update_members(
            URL=Field_Uri(value=self.assetUrl)
        )
        matRefList = [
            Reference(target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>",
                    target_id=matData.matComp.id
            ) for matData in self.matData
        ]
        if len(matRefList) == 0:
            matRefList = [
                Reference(
                    target_id=MaterialAssetSlotData.defaultMaterial.id,
                    target_type="[FrooxEngine]FrooxEngine.IAssetProvider<[FrooxEngine]FrooxEngine.Material>"
                )
            ]
        await self.meshRenderer.update_members(
            Materials=SyncList(
                *matRefList
            ),
            Enabled=Field_Bool(value=not self.hidden)
        )

    async def addMaterialAsync(self, mat : bpy.types.Material, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        matSlotData = MaterialAssetSlotData.Get(mat)
        if matSlotData is None:
            matSlotData = MaterialAssetSlotData(mat)
            await matSlotData.instantiateAsync(client, context)
        else:
            try:
                await matSlotData.updateAsync(client, context)
            except ResoniteLinkException:
                await matSlotData.instantiateAsync(client, context)
        
        if not matSlotData in self.matData:
            self.matData.append(matSlotData)
    

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
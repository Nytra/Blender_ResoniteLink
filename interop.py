# Blender Imports
from typing import Any

import bpy
from mathutils import Euler

# Resonitelink Imports
from resonitelink.models.datamodel import *
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy
from resonitelink import ResoniteLinkWebsocketClient

class ID_SlotData():

    idToSlotData : dict[bpy.types.ID, 'ID_SlotData'] = {}

    def __init__(self, id : bpy.types.ID):
        self.id : bpy.types.ID = id
        self.slot : SlotProxy = None
        ID_SlotData.idToSlotData[self.id] = self

    @classmethod
    def Get(cls, id : bpy.types.ID) -> 'ID_SlotData':
        if id in ID_SlotData.idToSlotData:
            return ID_SlotData.idToSlotData[id]
        else:
            return None
        
    @classmethod
    def Remove(cls, id : bpy.types.ID):
        if id in ID_SlotData.idToSlotData:
            ID_SlotData.idToSlotData.pop(id)

    # can be overriden if derived classes need more control over the creation of the slot
    async def instantiateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        self.slot = await client.add_slot(
                name=self.id.name,
                position=Float3(0, 0, 0),
                rotation=FloatQ(0, 0, 0, 1),
                scale=Float3(1, 1, 1),
                tag=self.id.id_type
            )
        
    async def updateAsync(self, client : ResoniteLinkWebsocketClient, context : bpy.types.Context):
        await client.update_slot(
                    self.slot,
                    name=self.id.name
                )

    # async def createSlotAsync(self):
    #     pass

    # async def updateSlotAsync(self):
    #     pass

    # async def createOrUpdateSlotAsync(self):
    #     if not self.id in ID_SlotData.idToSlotData:
    #         await self.createSlotAsync()
    #     else:
    #         await self.updateSlotAsync()


class MaterialSlotData(ID_SlotData):

    def __init__(self, mat : bpy.types.Material):
        super().__init__(mat)
        self.diffuseColor = mat.diffuse_color
        self.textures = mat.texture_paint_slots
        
    @classmethod
    def Get(cls, mat : bpy.types.Material) -> 'MaterialSlotData':
        if mat in ID_SlotData.idToSlotData:
            return ID_SlotData.idToSlotData[mat]
        else:
            return None


class ObjectSlotData(ID_SlotData):

    def __init__(self, obj : bpy.types.Object):
        super().__init__(obj)

    @classmethod
    def Get(cls, obj : bpy.types.Object) -> 'ObjectSlotData':
        if obj in ID_SlotData.idToSlotData:
            return ID_SlotData.idToSlotData[obj]
        else:
            return None
        
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


class MeshSlotData(ObjectSlotData):

    def __init__(self, obj : bpy.types.Object):
        super().__init__(obj)
        self.meshComp : ComponentProxy = None
        self.matComps : list[ComponentProxy] = [] 
        self.meshRenderer : ComponentProxy = None
        self.hidden = False

    @classmethod
    def Get(cls, obj : bpy.types.Object) -> 'ObjectSlotData':
        if obj in ID_SlotData.idToSlotData:
            return ID_SlotData.idToSlotData[obj]
        else:
            return None
    
    async def addMaterialAsync(self):
        # TODO: Detect the material type
        mat_type = "[FrooxEngine]FrooxEngine.PBS_VertexColorMetallic"
        
        # TODO: Detect whether the material exists already
        matComp = await self.slot.add_component(mat_type)
        
        # Add the material to the slot
        self.matComps.append(matComp)  # TODO: Put this material on the assets slot in the world
    

class SceneSlotData(ID_SlotData):

    @classmethod
    def Get(cls, scene : bpy.types.Scene) -> 'SceneSlotData':
        if scene in ID_SlotData.idToSlotData:
            return ID_SlotData.idToSlotData[scene]
        else:
            return None


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
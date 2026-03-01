# Blender Imports
import bpy
from mathutils import Euler

# Resonitelink Imports
from resonitelink.proxies.datamodel.slot_proxy import SlotProxy
from resonitelink.proxies.datamodel.component_proxy import ComponentProxy

class ID_SlotData():

    idToSlotData : dict[bpy.types.ID, 'ID_SlotData'] = {}

    def __init__(self, id : bpy.types.ID, slotProxy : SlotProxy):
        self.id : bpy.types.ID = id
        self.slot : SlotProxy = slotProxy
        ID_SlotData.idToSlotData[self.id] = self

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

    # ToDo: probably should make the other classes follow this pattern with the Get classmethod
    #matToSlotData = dict[bpy.types.Material, 'MaterialSlotData'] = {}

    def __init__(self, mat : bpy.types.Material, slotProxy : SlotProxy):
        super().__init__(mat, slotProxy)
        self.diffuseColor = mat.diffuse_color
        self.textures = mat.texture_paint_slots
        
    @classmethod
    def Get(cls, mat : bpy.types.Material) -> 'MaterialSlotData':
        if mat in ID_SlotData.idToSlotData:
            return ID_SlotData.idToSlotData[mat]
        else:
            return None


class ObjectSlotData(ID_SlotData):

    def __init__(self, obj : bpy.types.Object, slotProxy : SlotProxy):
        super().__init__(obj, slotProxy)

    def GetObject(self) -> bpy.types.Object:
        return self.id
    
    def GetData(self) -> bpy.types.ID:
        return self.id.data


class MeshSlotData(ObjectSlotData):

    def __init__(self, obj : bpy.types.Object, slotProxy : SlotProxy):
        super().__init__(obj, slotProxy)
        self.meshComp : ComponentProxy = None
        self.matComps : list[ComponentProxy] = [] 
        self.meshRenderer : ComponentProxy = None
        self.hidden = False
    

class SceneSlotData(ID_SlotData):

    pass


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
from fastapi import FastAPI, HTTPException
from typing import List, Optional
from pydantic import BaseModel
import requests
from fastapi.middleware.cors import CORSMiddleware
import json
import io
import logging
# new package for cron task
import aiocron
import aiohttp
from datetime import datetime, time

API_KEY = 'cf3197ee7b0a4f38be6c4a637d69fd03'
BASE_URL = 'https://api.spoonacular.com'

app = FastAPI()

#Your free instance will spin down with inactivity, which can delay requests by 50 seconds or more.
#so we self ping between the active hours to avoid the delay. 
''' 
async def is_active_hours():
    now = datetime.now().time()
    return time(9,0) <= now <= time(18,0) # assume active time between 9:00 and 18:00
'''
@aiocron.crontab('*/10 * * * *')
async def self_ping():
    async with aiohttp.ClientSession() as session:
        async with session.get('https://generaterecipe.onrender.com/health') as response:
            print(f"Health check response: {response.status}")
   
@app.on_event("startup")
async def startup_event():
    self_ping.start()


# set log
# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define Pydantic models
class NutritionalInfo(BaseModel):
    Calories: Optional[str] = None
    Carbohydrates: Optional[str] = None
    Fat: Optional[str] = None
    Protein: Optional[str] = None

class RecipeDetail(BaseModel):
    title: str
    ingredients: List[str]
    instructions: Optional[str] = 'No instructions available'
    nutritional_info: NutritionalInfo
    used_ingredients: List[str]
    missing_ingredients: List[str]
    image_url: Optional[str] = None

class RecipeSearchRequest(BaseModel):
    ingredients: List[str]
    number_of_recipes: Optional[int] = 5

# Function to search for recipes based on ingredients
def search_recipes_by_ingredients(ingredients: List[str], number_of_recipes: int = 5):
    search_url = f"{BASE_URL}/recipes/findByIngredients"
    params = {
        'ingredients': ','.join(ingredients),
        'number': number_of_recipes,
        'apiKey': API_KEY
    }
    response = requests.get(search_url, params=params)
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 402:
        logger.error(f"API quota exceeded or invalid API key: {response.text}")
        raise HTTPException(status_code=402, detail="API quota exceeded or invalid API key")
    else:
        logger.error(f"Error fetching recipes: {response.status_code} - {response.text}")
        raise HTTPException(status_code=response.status_code, detail="Error fetching recipes")

# Function to get detailed recipe information including nutritional info
def get_recipe_details(recipe_id: int):
    recipe_url = f"{BASE_URL}/recipes/{recipe_id}/information"
    params = {
        'includeNutrition': 'true',
        'apiKey': API_KEY
    }
    response = requests.get(recipe_url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching details for recipe ID {recipe_id}")

# Function to extract main nutritional info: Calories, Carbs, Fat, Protein
def extract_main_nutritional_info(nutrition):
    nutrients = nutrition.get('nutrients', [])
    main_info = {}
    for nutrient in nutrients:
        name = nutrient['name']
        if name in ['Calories', 'Carbohydrates', 'Fat', 'Protein']:
            main_info[name] = f"{nutrient['amount']} {nutrient['unit']}"
    return NutritionalInfo(**main_info)

@app.post("/recipes/", response_model=List[RecipeDetail])
async def get_recipes(request: RecipeSearchRequest):
    try:
        recipes = search_recipes_by_ingredients(request.ingredients, request.number_of_recipes)
        detailed_recipes = []
        for recipe in recipes:
            recipe_id = recipe['id']
            recipe_details = get_recipe_details(recipe_id)
            
            # Extract used and missing ingredients from the search response
            used_ingredients = recipe.get('usedIngredients', [])
            missing_ingredients = recipe.get('missedIngredients', [])
            
            detailed_recipes.append({
                'title': recipe_details['title'],
                'ingredients': [ingredient['name'] for ingredient in recipe_details['extendedIngredients']],
                'instructions': recipe_details.get('instructions', 'No instructions available'),
                'nutritional_info': extract_main_nutritional_info(recipe_details['nutrition']),
                'used_ingredients': [ingredient['name'] for ingredient in used_ingredients],
                'missing_ingredients': [ingredient['name'] for ingredient in missing_ingredients],
                'image_url': recipe_details.get('image', None)
            })
        
        return detailed_recipes
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}